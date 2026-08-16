#!/usr/bin/env python3
"""
AIHOT 热点资讯查询脚本
调用 aihot.virxact.com API 获取 AI 动态
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
BASE_URL = "https://aihot.virxact.com/api/public"


def fetch_items(query="AI", limit=20, category="", since_days=1):
    params = {
        "mode": "selected",
        "take": min(limit, 100),
    }
    if category:
        params["category"] = category
    if query:
        params["q"] = query

    # since 时间窗
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params["since"] = since

    url = f"{BASE_URL}/items?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            return data.get("items", [])
    except Exception as e:
        print(f"[ERROR] AIHOT API error: {e}", file=sys.stderr)
        return []


def format_time(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
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


def format_output(items, query=""):
    lines = [
        f"**AI HOT — 最近 24 小时精选**",
        f"关键词: {query}  |  共 {len(items)} 条",
        "",
    ]

    for i, item in enumerate(items, 1):
        title = item.get("title", "")
        source = item.get("source", "")
        published = format_time(item.get("publishedAt", ""))
        summary = item.get("summary", "")
        url = item.get("url", "")

        category = item.get("category", "")
        cat_label = {
            "ai-models": "模型发布/更新",
            "ai-products": "产品发布/更新",
            "industry": "行业动态",
            "paper": "论文研究",
            "tip": "技巧与观点",
        }.get(category, "")

        lines.append(f"{i}. **{title}** — {source}")
        lines.append(f"   {published}")
        if summary:
            lines.append(f"   {summary[:200]}")
        if url:
            lines.append(f"   {url}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AIHOT 热点资讯查询")
    parser.add_argument("query", nargs="?", default="AI", help="搜索关键词")
    parser.add_argument("limit", nargs="?", type=int, default=20, help="返回数量")
    parser.add_argument("--category", "-c", default="", help="分类过滤")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = parser.parse_args()

    items = fetch_items(args.query, args.limit, args.category)

    if not items:
        print("未获取到数据", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        print(format_output(items, args.query))


if __name__ == "__main__":
    main()
