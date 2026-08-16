#!/usr/bin/env python3
"""
工作台云同步数据仓库（2026-08-05 新增 · B 方案）
2026-08-16 改造 · 统一写到 Obsidian vault 的「工作台缓存」目录
  原因：原本 web 端私存到 api/data/store.json，PC 端 sharedStore 写到 vault 的工作台数据.json
        两份文件完全不通，手机/电脑数据分裂。
  方案：放弃 web 私存路径，全部走 vault，与 PC 端 Obsidian 插件共用一份。

存储：📚 知识库/04 - Archive 归档/工作台缓存/工作台数据.json
     （结构 {key: value}，原子写）
"""
import json
from pathlib import Path

# 真源：Obsidian vault 工作台缓存目录（与 PC 端 sharedStore.ts 一致）
VAULT_CACHE_DIR = Path("/mnt/d/Obsidian Vault/📚 知识库/04 - Archive 归档/工作台缓存")
STORE_PATH = VAULT_CACHE_DIR / "工作台数据.json"
STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_store() -> dict:
    if STORE_PATH.exists():
        try:
            data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_store(data: dict) -> None:
    """原子写 store.json（先写临时文件再 replace，崩溃不丢数据）"""
    tmp = STORE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE_PATH)


def get_store() -> dict:
    return _load_store()


def put_key(key: str, value) -> None:
    """写入单个 key"""
    data = _load_store()
    data[key] = value
    _save_store(data)


def put_many(entries: dict) -> int:
    """批量合并写入（首次迁移用）。返回实际写入的 key 数"""
    data = _load_store()
    count = 0
    for k, v in entries.items():
        if k:
            data[k] = v
            count += 1
    _save_store(data)
    return count


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "get"
    if cmd == "get":
        print(json.dumps(get_store(), ensure_ascii=False, indent=2))
    elif cmd == "put" and len(sys.argv) >= 4:
        print("written:", put_key(sys.argv[2], sys.argv[3]))
    else:
        print("usage: python3 sync_store.py [get | put key value]")
