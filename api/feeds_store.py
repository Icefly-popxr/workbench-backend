#!/usr/bin/env python3
"""
工作台 feeds 推送接口 / 文件工具
2026-08-16 改造 · feeds.json 迁到 Obsidian vault「工作台缓存」目录
  与 PC 端 info-tracker / newsService 走 vault 同一份数据。
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 真源：Obsidian vault 工作台缓存目录（与 PC 端 newsService.ts 一致）
VAULT_CACHE_DIR = Path("/mnt/d/Obsidian Vault/📚 知识库/04 - Archive 归档/工作台缓存")
FEEDS_PATH = VAULT_CACHE_DIR / "feeds.json"
FEEDS_PATH.parent.mkdir(parents=True, exist_ok=True)


def _now_iso():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def _load_feeds():
    if FEEDS_PATH.exists():
        try:
            return json.loads(FEEDS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


# 每个分类最多保留的条数（超出裁剪最旧的，防止文件无限膨胀）
MAX_FEEDS_PER_CATEGORY = 300


def _save_feeds(feeds):
    """原子写 feeds.json（先写临时文件再 rename，崩溃也不会留下半个文件）"""
    tmp = FEEDS_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(feeds, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(FEEDS_PATH)


def append_feeds(items, category="ai"):
    """追加 feeds 条目（按 url 去重 + 每分类条数上限裁剪）
    items: list[dict] 至少含 title / url / source
    category: ai | stock | politics | finance | subs
    返回：本次新增的条数
    """
    feeds = _load_feeds()
    now = _now_iso()

    # 已有 url 集合，用于跨天重复推送去重
    seen_urls = {f.get("url") for f in feeds if f.get("url")}

    added = []
    for it in items:
        if not (it.get("title") or it.get("url")):
            continue
        url = it.get("url", "")
        if url and url in seen_urls:
            continue  # 同一条新闻不重复入库
        if url:
            seen_urls.add(url)
        added.append({
            "id": f"{int(datetime.now().timestamp() * 1000)}_{len(added)}",
            "category": category,
            "title": it.get("title", ""),
            "url": url,
            "source": it.get("source", ""),
            "summary": it.get("summary", ""),
            "createdAt": now,
        })

    feeds.extend(added)

    # 每分类裁剪：只保留最新的 MAX_FEEDS_PER_CATEGORY 条
    by_cat: dict[str, list[dict]] = {}
    for f in feeds:
        by_cat.setdefault(f.get("category", ""), []).append(f)
    trimmed = []
    for cat, items_in_cat in by_cat.items():
        items_in_cat.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        trimmed.extend(items_in_cat[:MAX_FEEDS_PER_CATEGORY])

    _save_feeds(trimmed)
    return len(added)


def get_latest_feeds(category=None, limit=50):
    feeds = _load_feeds()
    if category:
        feeds = [f for f in feeds if f.get("category") == category]
    feeds = sorted(feeds, key=lambda x: x.get("createdAt", ""), reverse=True)[:limit]
    return {"feeds": feeds, "count": len(feeds)}


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "append":
        print(append_feeds([{"title": "test", "url": "https://example.com", "source": "test"}]))
    else:
        print(json.dumps(get_latest_feeds(), ensure_ascii=False, indent=2))
