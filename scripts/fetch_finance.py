#!/usr/bin/env python3
"""
财经资讯采集脚本（2026-08-05 落地）
源头：① 36kr 通用 RSS（实测 200，含大量财经/创投）
备选：财联社 SPA 端点（被 Cloudflare 拦截，弃用）
输出：stdout JSON list → 走 dashboard_push.py 推送到 feeds.json（category=finance）

使用：
  python3 fetch_finance.py [--limit 10] | python3 dashboard_push.py finance
  python3 fetch_finance.py --dry-run  # 调试
"""
import argparse
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# 36kr 通用 RSS（财经/创投/科技综合，可作财经主要源）
KR36_RSS = "https://www.36kr.com/feed"

# 关键词：财经相关
FINANCE_KEYWORDS = re.compile(
    r"财经|金融|股票|股市|A股|港股|美股|基金|理财|融资|IPO|上市|"
    r"投资|创投|VC|PE|并购|收购|重组|"
    r"公司|营收|利润|财报|季报|年报|"
    r"央行|货币政策|利率|汇率|通胀|"
    r"消费|零售|电商|订单|品牌|"
    r"美元|人民币|外汇|黄金|油价|期货|债券",
    re.IGNORECASE
)


def fetch_kr36_finance():
    """36kr RSS，过滤出财经/创投相关"""
    req = urllib.request.Request(KR36_RSS, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read()
    except Exception as e:
        print(f"[ERROR] 36kr RSS: {e}", file=sys.stderr)
        return []
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    try:
        root = ET.fromstring(content)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub_str = (item.findtext("pubDate") or "").strip()
            if not title or not link:
                continue
            # 时间过滤（最近 7 天）
            pub_dt = None
            if pub_str:
                try:
                    pub_dt = parsedate_to_datetime(pub_str)
                except Exception:
                    pub_dt = None
            if pub_dt and pub_dt < cutoff:
                continue
            if FINANCE_KEYWORDS.search(title):
                items.append({
                    "title": title,
                    "url": link.split("?")[0],
                    "source": "36kr",
                    "summary": re.sub(r"<[^>]+>", "", desc)[:200],
                })
    except ET.ParseError as e:
        print(f"[ERROR] 36kr RSS parse: {e}", file=sys.stderr)
    return items


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", "-n", type=int, default=10)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    items = fetch_kr36_finance()

    # 去重（按 URL）
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