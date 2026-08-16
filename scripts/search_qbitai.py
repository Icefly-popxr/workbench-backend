#!/usr/bin/env python3
"""
量子位 AI 资讯 RSS 抓取脚本
抓取 https://www.qbitai.com/feed 的最新文章
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
FEED_URL = "https://www.qbitai.com/feed"


def fetch_feed(limit=20, since_days=1):
    """抓取量子位 RSS"""
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_bytes = resp.read()
    except Exception as e:
        print(f"[ERROR] 量子位 RSS 抓取失败: {e}", file=sys.stderr)
        return []

    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        print(f"[ERROR] 量子位 RSS XML 解析失败: {e}", file=sys.stderr)
        return []

    # 抓取时间窗
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_str = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()
        creator = item.findtext("{http://purl.org/dc/elements/1.1/}creator") or ""
        creator = creator.strip()

        # 分类（可能有多个 <category>）
        cats = [c.text.strip() for c in item.findall("category") if c.text]

        # 时间过滤
        try:
            pub_dt = parsedate_to_datetime(pub_str)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            pub_dt = None

        if pub_dt and pub_dt < cutoff:
            continue

        # 摘要清洗
        summary = re.sub(r"<[^>]+>", "", desc).strip()[:300]

        items.append({
            "title": title,
            "url": link,
            "publishedAt": pub_str,
            "summary": summary,
            "source": "量子位",
            "category": ",".join(cats) if cats else "",
            "author": creator,
        })

    return items[:limit]


def format_time(iso_str):
    try:
        dt = parsedate_to_datetime(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
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
    lines = [f"**量子位 — 最近 {len(items)} 条 AI 资讯**", ""]
    for i, item in enumerate(items, 1):
        title = item.get("title", "")
        published = format_time(item.get("publishedAt", ""))
        summary = item.get("summary", "")
        url = item.get("url", "")
        cat = item.get("category", "")
        author = item.get("author", "")

        lines.append(f"{i}. **{title}**")
        meta = []
        if author:
            meta.append(author)
        if cat:
            meta.append(cat)
        meta.append(published)
        lines.append(f"   {'  |  '.join(meta)}")
        if summary:
            lines.append(f"   {summary[:150]}")
        if url:
            lines.append(f"   {url}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="量子位 AI 资讯查询")
    parser.add_argument("--limit", "-n", type=int, default=20)
    parser.add_argument("--since-days", "-d", type=int, default=1)
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = parser.parse_args()

    items = fetch_feed(args.limit, args.since_days)
    if not items:
        print("未获取到数据", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        print(format_output(items))


if __name__ == "__main__":
    main()