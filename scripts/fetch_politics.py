#!/usr/bin/env python3
"""
时政资讯采集脚本（2026-08-05 落地）
源头：① 人民网时政 RSS（http://www.people.com.cn/rss/politics.xml）
     ② 中新网时政 RSS（https://www.chinanews.com/rss/china.xml）
     ③ 知乎热榜 API（https://api.zhihu.com/topstory/hot-lists/total）
     ④ 36kr 通用 RSS（https://www.36kr.com/feed）+ 时政关键词过滤（fallback）
注：新华网 RSS 已停更（pubDate 缺失/2022 旧数据），函数保留作骨架
输出：stdout JSON list → 走 dashboard_push.py 推送到 feeds.json（category=politics）

使用：
  python3 fetch_politics.py [--limit 10] | python3 dashboard_push.py politics
  python3 fetch_politics.py --dry-run  # 调试
"""
import argparse
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# 知乎热榜 API（实测 200 · 2026-08-05 重新发现）
ZHIHU_HOT_API = "https://api.zhihu.com/topstory/hot-lists/total?limit=30&desktop=true"
# 人民网时政 RSS（实测 200 + 数据活）
PEOPLE_RSS = "http://www.people.com.cn/rss/politics.xml"
# 中新网时政 RSS（实测 200 + 数据活）
CHINANEWS_RSS = "https://www.chinanews.com/rss/china.xml"
# 36kr 通用 RSS（财经为主，过滤时政关键词作 fallback）
KR36_RSS = "https://www.36kr.com/feed"

# 时政相关关键词（仅给知乎 + 36kr 用，人民网/中新网是纯时政频道不需要过滤）
POLITICS_KEYWORDS = re.compile(
    r"国务院|政策|政府|中央|国家|主席|总理|人大|政协|"
    r"外交|国际|外交部|美国|俄罗斯|欧盟|制裁|战争|"
    r"党|中共|纪委|监察|巡视|"
    r"改革|法律|立法|司法|法院|检察|"
    r"上海|北京|深圳|广州|杭州|成都|重庆|天津|南京",
    re.IGNORECASE
)

# 排除词（娱乐/体育等完全无关）
EXCLUDE_KEYWORDS = re.compile(
    r"娱乐|明星|综艺|电视剧|电影|",
    re.IGNORECASE
)


def _parse_pubdate(s):
    """支持 RFC 822 (Wed, 5 Aug 2026 14:12:48 +0800) 和 YYYY-MM-DD 两种格式
    解析失败返回 None（表示"无法判断 → 保守拒绝"）"""
    if not s:
        return None
    # 先试 RFC 822
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    # 再试 YYYY-MM-DD
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _within_30_days(dt):
    """30 天过滤 · 无 pubDate 一律拒绝（保守，避免 2022 旧数据混进）"""
    if not dt:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    return dt >= cutoff


def _within_7_days(dt):
    """7 天过滤 · 无 pubDate 一律拒绝"""
    if not dt:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    return dt >= cutoff


def fetch_zhihu_hot():
    """拉知乎热榜 top30（已切换到 api.zhihu.com 直连）"""
    req = urllib.request.Request(ZHIHU_HOT_API, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[ERROR] zhihu API: {e}", file=sys.stderr)
        return []
    items = []
    for it in data.get("data", []):
        target = it.get("target", {})
        title = target.get("title", "").strip()
        if not title:
            continue
        qid = target.get("id", "")
        url = f"https://www.zhihu.com/question/{qid}" if qid and target.get("type") == "question" else target.get("url", "")
        if not url:
            continue
        if POLITICS_KEYWORDS.search(title) and not EXCLUDE_KEYWORDS.search(title):
            items.append({"title": title, "url": url, "source": "知乎热榜"})
    return items


def fetch_people_rss():
    """人民网时政 RSS（全收，频道本身就是时政）"""
    req = urllib.request.Request(PEOPLE_RSS, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read()
    except Exception as e:
        print(f"[ERROR] people RSS: {e}", file=sys.stderr)
        return []
    items = []
    try:
        root = ET.fromstring(content)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            if not (title and link):
                continue
            if not _within_7_days(_parse_pubdate((item.findtext("pubDate") or "").strip())):
                continue
            items.append({
                "title": title,
                "url": link,
                "source": "人民网",
                "summary": re.sub(r"<[^>]+>", "", desc)[:200],
            })
    except ET.ParseError as e:
        print(f"[ERROR] people RSS parse: {e}", file=sys.stderr)
    return items


def fetch_chinanews_rss():
    """中新网时政 RSS（全收）"""
    req = urllib.request.Request(CHINANEWS_RSS, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read()
    except Exception as e:
        print(f"[ERROR] chinanews RSS: {e}", file=sys.stderr)
        return []
    items = []
    try:
        root = ET.fromstring(content)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            if not (title and link):
                continue
            if not _within_7_days(_parse_pubdate((item.findtext("pubDate") or "").strip())):
                continue
            items.append({
                "title": title,
                "url": link,
                "source": "中新网",
                "summary": re.sub(r"<[^>]+>", "", desc)[:200],
            })
    except ET.ParseError as e:
        print(f"[ERROR] chinanews RSS parse: {e}", file=sys.stderr)
    return items


def fetch_kr36_filtered():
    """36kr RSS 兜底，只收时政相关"""
    req = urllib.request.Request(KR36_RSS, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read()
    except Exception as e:
        print(f"[ERROR] 36kr RSS: {e}", file=sys.stderr)
        return []
    items = []
    try:
        root = ET.fromstring(content)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            if not (title and link):
                continue
            if not _within_7_days(_parse_pubdate((item.findtext("pubDate") or "").strip())):
                continue
            if POLITICS_KEYWORDS.search(title) and not EXCLUDE_KEYWORDS.search(title):
                items.append({
                    "title": title,
                    "url": link.split("?")[0],
                    "source": "36kr",
                    "summary": re.sub(r"<[^>]+>", "", desc)[:200],
                })
    except ET.ParseError as e:
        print(f"[ERROR] 36kr RSS parse: {e}", file=sys.stderr)
    return items


def fetch_xinhua_rss():
    """新华网时政 RSS 占位 · 2026-08-05 实测 RSS 已停更（pubDate 缺失/2022 旧数据）"""
    print("[INFO] xinhua RSS 已停更（pubDate 缺失），跳过", file=sys.stderr)
    return []


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", "-n", type=int, default=10)
    p.add_argument("--dry-run", action="store_true", help="只打印不推送")
    p.add_argument("--source", default="all", choices=["all", "zhihu", "people", "chinanews", "kr36", "xinhua"])
    args = p.parse_args()

    items = []
    if args.source in ("all", "people"):
        items.extend(fetch_people_rss())
    if args.source in ("all", "chinanews"):
        items.extend(fetch_chinanews_rss())
    if args.source in ("all", "xinhua"):
        items.extend(fetch_xinhua_rss())
    if args.source in ("all", "kr36"):
        items.extend(fetch_kr36_filtered())
    if args.source in ("all", "zhihu"):
        items.extend(fetch_zhihu_hot())

    # 去重（同 URL 不重复）
    seen = set()
    dedup = []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        dedup.append(it)
        if len(dedup) >= args.limit:
            break

    if args.dry_run:
        print(json.dumps(dedup, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(0)

    print(json.dumps(dedup, ensure_ascii=False))


if __name__ == "__main__":
    main()