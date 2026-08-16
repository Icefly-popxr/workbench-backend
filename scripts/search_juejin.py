#!/usr/bin/env python3
"""
稀土掘金热榜 RSS 抓取脚本
抓取 https://juejin.cn/rss 的最新文章
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
FEED_URL = "https://juejin.cn/rss"


def fetch_feed(limit=20, since_days=1, ai_only=True):
    """抓取掘金 RSS

    ai_only=True 只保留 AI 相关分类的文章（category 包含 Ai/ai 等关键词）。
    """
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_bytes = resp.read()
    except Exception as e:
        print(f"[ERROR] 掘金 RSS 抓取失败: {e}", file=sys.stderr)
        return []

    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        print(f"[ERROR] 掘金 RSS XML 解析失败: {e}", file=sys.stderr)
        return []

    # 抓取时间窗
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    items = []
    ai_keywords = ["AI", "ai", "人工智能", "大模型", "LLM", "Agent", "agent",
                   "机器学习", "深度学习", "神经网络", "GPT", "Claude", "ChatGPT",
                   "LangChain", "RAG", "LLM", "LLMs"]

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_str = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()

        # 时间过滤
        try:
            pub_dt = datetime.strptime(pub_str, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        except Exception:
            try:
                pub_dt = datetime.strptime(pub_str, "%a, %d %b %Y %H:%M:%S %+z")
            except Exception:
                pub_dt = None

        if pub_dt and pub_dt < cutoff:
            continue

        # AI 过滤：基于标题+摘要关键词
        if ai_only:
            combined = title + " " + desc
            if not any(kw in combined for kw in ai_keywords):
                continue

        # 摘要清洗（去掉 HTML 标签）
        summary = re.sub(r"<[^>]+>", "", desc).strip()[:300]

        items.append({
            "title": title,
            "url": link,
            "publishedAt": pub_str,
            "summary": summary,
            "source": "稀土掘金",
            "category": "AI",
        })

    return items[:limit]


def format_time(iso_str):
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(iso_str)
        bjt = dt.astimezone(timezone(timedelta(hours=8)))
        now = datetime.now(timezone(timedelta(hours=8)))
        diff = now - bjt
        if diff.total_seconds() < 3600:
            return f"{int(diff.total_seconds() / 60)} 分钟前"
        elif diff.total_seconds() < 86400:
            return f"{int(diff.total_seconds() / 3600)} 小时前"
        else:
            return bjt.strftime("%m-%d %H:%M")
    except Exception:
        return iso_str


def format_output(items):
    lines = [f"**稀土掘金热榜 — 最近 {len(items)} 条 AI 相关**", ""]
    for i, item in enumerate(items, 1):
        title = item.get("title", "")
        published = format_time(item.get("publishedAt", ""))
        summary = item.get("summary", "")
        url = item.get("url", "")
        cat = item.get("category", "")

        lines.append(f"{i}. **{title}**")
        if cat:
            lines.append(f"   分类: {cat}  |  {published}")
        else:
            lines.append(f"   {published}")
        if summary:
            lines.append(f"   {summary[:150]}")
        if url:
            lines.append(f"   {url}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="稀土掘金热榜查询")
    parser.add_argument("--limit", "-n", type=int, default=20)
    parser.add_argument("--since-days", "-d", type=int, default=1)
    parser.add_argument("--ai-only", action="store_true", default=True,
                        help="只保留 AI 相关分类（默认 True）")
    parser.add_argument("--no-ai-filter", dest="ai_only", action="store_false")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = parser.parse_args()

    items = fetch_feed(args.limit, args.since_days, args.ai_only)
    if not items:
        print("未获取到数据", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        print(format_output(items))


if __name__ == "__main__":
    main()