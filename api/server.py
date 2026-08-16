#!/usr/bin/env python3
"""
工作台后端服务 · 然哥的工作台
监听 0.0.0.0:8765 · Tailscale 内网可访问
- GET  /api/kc/cards       全部 KC 卡片（含复习状态）
- GET  /api/kc/stats       统计
- GET  /api/kc/card?id=X   单张卡全文
- GET  /api/review/today   今日待复习
- POST /api/review/mark    标记某张 KC 复习过（写 review-state.json）

跨域已开（工作台 PWA fetch 本机端口需要 CORS）
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP server：每个请求独立线程处理，单连接卡死不影响其他请求"""
    daemon_threads = True  # 主线程退出时子线程也退出
from pathlib import Path
from collections import defaultdict
from urllib.parse import urlparse, parse_qs
import urllib.request
import uuid

# 导入同目录的 scan_kc
sys.path.insert(0, str(Path(__file__).parent))
from scan_kc import (
    list_cards_with_state,
    get_stats,
    get_today_review,
    read_kc_card_full,
    load_review_state,
    pick_review_state_path,
    derive_card_state,
)
from feeds_store import append_feeds, get_latest_feeds
from sync_store import get_store, put_key, put_many

HOST = "0.0.0.0"
PORT = 8765

# ============= 标准发音 TTS（2026-08-06 新增）=============
# 用 edge-tts（微软 Edge 同款神经网络语音）生成标准美音 mp3，
# 手机朗读与电脑发音一致。缓存到 api/data/tts_cache/。
TTS_CACHE_DIR = Path(__file__).parent / "data" / "tts_cache"
TTS_VOICE = "en-US-JennyNeural"

# ============= Obsidian 工作台配置（2026-08-06 新增）=============
# Obsidian 插件在 vault 里维护《工作台配置.json》，Web 端读取同一份配置渲染。
DASHBOARD_CONFIG_WSL = Path("/mnt/d/Obsidian Vault/00_工具/工作台配置.json")
DASHBOARD_CONFIG_WIN = Path("D:/Obsidian Vault/00_工具/工作台配置.json")

# ============= 共享数据文件（2026-08-07 新增）=============
# 数据统一到 vault：插件与 Web 端共用《工作台数据.json》（只维护一份）。
# 读优先 vault 共享文件，写也写 vault 共享文件；vault 不存在时回退 api/data/store.json。
# ★ 插件实际运行在 OneDrive 同步的 vault（D:/Obsidian Vault 为旧路径，保留兜底）。
DASHBOARD_SHARED_WSL = Path("/mnt/c/Users/IceFly/OneDrive/应用/remotely-save/Obsidian Vault/00_工具/工作台数据.json")
DASHBOARD_SHARED_WIN = Path("C:/Users/IceFly/OneDrive/应用/remotely-save/Obsidian Vault/00_工具/工作台数据.json")
DASHBOARD_SHARED_LEGACY_WSL = Path("/mnt/d/Obsidian Vault/00_工具/工作台数据.json")
DASHBOARD_SHARED_LEGACY_WIN = Path("D:/Obsidian Vault/00_工具/工作台数据.json")
STORE_FALLBACK = Path(__file__).parent / "data" / "store.json"

# ★ 2026-08-10 打通 PC 端 Obsidian 插件 knowledge-workbench：
#   插件实际写入《📚 知识库/04 - Archive 归档/工作台缓存/工作台数据.json》，
#   本后端改为读写同一份文件（win 路径给 Windows 运行时，wsl 路径给 WSL 运行时），
#   并在 /api/store 边界做 key 翻译（Web 命名 ↔ PC 命名），实现两端数据互通。
DASHBOARD_PC_CACHE_WIN = Path("D:/Obsidian Vault/📚 知识库/04 - Archive 归档/工作台缓存/工作台数据.json")
DASHBOARD_PC_CACHE_WSL = Path("/mnt/d/Obsidian Vault/📚 知识库/04 - Archive 归档/工作台缓存/工作台数据.json")

# ★ 2026-08-10 打通：读取 PC 端插件设置（播客下载目录、确认开关、笔记目录等）
VAULT_ROOT_WIN = Path("D:/Obsidian Vault")
VAULT_ROOT_WSL = Path("/mnt/d/Obsidian Vault")
PLUGIN_DATA_JSON_WIN = VAULT_ROOT_WIN / ".obsidian" / "plugins" / "knowledge-workbench" / "data.json"
PLUGIN_DATA_JSON_WSL = VAULT_ROOT_WSL / ".obsidian" / "plugins" / "knowledge-workbench" / "data.json"


def _pick_shared_path() -> Path | None:
    """优先返回共享文件路径。
    ★ 2026-08-10 打通：PC 端 Obsidian 插件 knowledge-workbench 实际写入
      《📚 知识库/04 - Archive 归档/工作台缓存/工作台数据.json》，本后端优先读它，
      实现 Web 端 ↔ PC 端数据互通（key 在 /api/store 边界翻译）。
    """
    for p in (
        DASHBOARD_PC_CACHE_WIN,
        DASHBOARD_PC_CACHE_WSL,
        DASHBOARD_SHARED_WSL,
        DASHBOARD_SHARED_WIN,
        DASHBOARD_SHARED_LEGACY_WSL,
        DASHBOARD_SHARED_LEGACY_WIN,
    ):
        try:
            if p.exists():
                return p
        except Exception:
            continue
    # 文件尚不存在但目录存在：返回该路径（写入时自动创建）
    for p in (
        DASHBOARD_PC_CACHE_WIN,
        DASHBOARD_PC_CACHE_WSL,
        DASHBOARD_SHARED_WSL,
        DASHBOARD_SHARED_WIN,
        DASHBOARD_SHARED_LEGACY_WSL,
        DASHBOARD_SHARED_LEGACY_WIN,
    ):
        try:
            if p.parent.exists():
                return p
        except Exception:
            continue
    return None


# Web 端私有键（只活在浏览器 localStorage，不应常驻 PC 共享文件，避免污染 / 互相覆盖）
WEB_PRIVATE_JUNK = {
    "podcast_rate", "podcast_stat", "podcast_progress",
    "workout_music_state", "workout_music_url", "workout_music_vol",
}


def _strip_junk(data: dict) -> dict:
    """剔除 Web 私有键"""
    for k in WEB_PRIVATE_JUNK:
        data.pop(k, None)
    return data


def get_shared_store() -> dict:
    """读取共享数据：优先 vault 共享文件，回退 store.json"""
    p = _pick_shared_path()
    if p is not None:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _strip_junk(data)
            return {}
        except Exception:
            return {}
    return get_store()


def put_shared_key(key: str, value) -> None:
    """写单个 key：只写 vault 共享文件（原子）。store.json 已废弃，不再回写。"""
    p = _pick_shared_path()
    if p is None:
        raise FileNotFoundError("未找到 vault 共享目录，无法写入")
    data = get_shared_store()
    data[key] = value
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def put_shared_many(entries: dict) -> int:
    """批量合并写入：只写 vault 共享文件（原子）。store.json 已废弃，不再回写。"""
    count = 0
    p = _pick_shared_path()
    if p is None:
        raise FileNotFoundError("未找到 vault 共享目录，无法写入")
    data = get_shared_store()
    for k, v in entries.items():
        if k:
            data[k] = v
            count += 1
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return count


# ============= 2026-08-10 打通：Web ↔ PC 命名翻译 =============
# Web 端 store 命名（index.html 的 SYNC_KEYS / SYNC_PREFIXES）：
#   stock_pool / topic_pool / english_records / today_done:<date> / workout_sessions:<date>
# PC 端 共享文件命名（knowledge-workbench SharedData）：
#   stockPool / topicPool / englishRecords / todayTodos(dict) / workoutSessions(list)
def _web_ep_to_pc(it):
    """Web 单集(podcast_list 项) → PC SharedPodcast。仅外链(http/https)可跨端播放；
    本地 IndexedDB(file) 与后端共享(/audio/) 属设备/后端局部，PC 无法播放 → 返回 None 跳过。"""
    if not isinstance(it, dict):
        return None
    url = (it.get("url") or "").strip()
    if it.get("file") or it.get("shared") or not url:
        return None
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    pc = {"id": it.get("id") or ("web_" + uuid.uuid4().hex),
          "title": it.get("title", ""),
          "src": url,
          "kind": "url"}
    if it.get("show"): pc["show"] = it["show"]
    if it.get("subId"): pc["subId"] = it["subId"]
    if it.get("listened") is not None: pc["listened"] = bool(it["listened"])
    if it.get("plays"): pc["plays"] = it["plays"]
    if it.get("addedAt"): pc["addedAt"] = it["addedAt"]
    if it.get("duration"): pc["duration"] = it["duration"]
    return pc


def _pc_ep_to_web(ep):
    """PC SharedPodcast → Web 单集。仅 kind:'url'(外链) 跨端可播放；kind:'vault'(vault 局部) 跳过。"""
    if not isinstance(ep, dict):
        return None
    if ep.get("kind") != "url":
        return None
    src = (ep.get("src") or "").strip()
    if not src:
        return None
    web = {"id": ep.get("id") or ("pc_" + uuid.uuid4().hex),
           "title": ep.get("title", ""),
           "url": src}
    if ep.get("show"): web["show"] = ep["show"]
    if ep.get("listened") is not None: web["listened"] = bool(ep["listened"])
    if ep.get("plays"): web["plays"] = ep["plays"]
    if ep.get("addedAt"): web["addedAt"] = ep["addedAt"]
    if ep.get("duration"): web["duration"] = ep["duration"]
    if ep.get("subId"): web["subId"] = ep["subId"]
    return web


def translate_pc_to_web(pc: dict) -> dict:
    """PC 共享文件(dict) → Web 端 store(dict)，供 GET /api/store 返回。"""
    web: dict = {}
    web["stock_pool"] = pc.get("stockPool") or []
    web["topic_pool"] = pc.get("topicPool") or []
    web["english_records"] = pc.get("englishRecords") or []
    # todayTodos: {date: [todos]} → 多个 today_done:<date> key
    for date, todos in (pc.get("todayTodos") or {}).items():
        web[f"today_done:{date}"] = {date: todos}
    # workoutSessions: [{date, min}] → 按日聚成 workout_sessions:<date>
    wd: dict = defaultdict(list)
    for s in (pc.get("workoutSessions") or []):
        if isinstance(s, dict) and s.get("date"):
            wd[s["date"]].append({"min": s.get("min", 0), "completedAt": s["date"] + "T00:00:00"})
    for date, sess in wd.items():
        web[f"workout_sessions:{date}"] = sess
    # 待办模板（Web 固定行程，PC 任务清单镜像展示）
    if pc.get("todayTemplate"):
        web["today_template"] = pc["todayTemplate"]
    # 临时待办（按日）
    for date, extras in (pc.get("todayExtra") or {}).items():
        web[f"today_extra:{date}"] = extras
    # 习惯镜像（PC 为准；Web Checkin UI 第二批消费）
    if pc.get("habits"):
        web["habits"] = pc["habits"]
    # 播客：PC podcasts → Web podcast_list（仅跨端可播放的外链 kind:'url'；vault 局部跳过）
    pcs = [_pc_ep_to_web(ep) for ep in (pc.get("podcasts") or [])]
    pcs = [p for p in pcs if p]
    # 播客相关设置同步到 Web（下载目录/确认开关/笔记目录）
    cfg = load_plugin_settings()
    web["podcast_settings"] = cfg
    if pcs:
        web["podcast_list"] = pcs
    # 速记（PC 为准，Web 端日迹轨道只读展示；结构同构直接下发）
    if pc.get("notes"):
        web["notes"] = pc["notes"]
    return web


def merge_web_to_pc(web_key: str, web_value) -> None:
    """Web 端推送的单 key（web 命名）合并进 PC 共享文件（pc 命名，原子写）。"""
    p = _pick_shared_path()
    if p is None:
        raise FileNotFoundError("未找到 vault 共享目录，无法写入")
    data = get_shared_store()
    if web_key == "stock_pool":
        data["stockPool"] = web_value if isinstance(web_value, list) else []
    elif web_key == "topic_pool":
        data["topicPool"] = web_value if isinstance(web_value, list) else []
    elif web_key == "english_records":
        # 按 date 去重合并，避免重复
        by_date = {r["date"]: r for r in data.get("englishRecords", []) if isinstance(r, dict) and r.get("date")}
        for r in (web_value or []):
            if isinstance(r, dict) and r.get("date"):
                by_date[r["date"]] = r
        data["englishRecords"] = list(by_date.values())
    elif web_key.startswith("today_done:"):
        date = web_key[len("today_done:"):]
        todos = web_value.get(date, web_value) if isinstance(web_value, dict) else (web_value or [])
        data.setdefault("todayTodos", {})[date] = todos
    elif web_key.startswith("workout_sessions:"):
        date = web_key[len("workout_sessions:"):]
        # 整日替换语义：先删该日旧记录，再写入
        sess = [s for s in data.get("workoutSessions", []) if isinstance(s, dict) and s.get("date") != date]
        for s in (web_value or []):
            if isinstance(s, dict):
                sess.append({"date": date, "min": s.get("min", 0)})
        data["workoutSessions"] = sess
    elif web_key == "today_template":
        # Web 固定行程模板（长期），PC 任务清单只读镜像
        data["todayTemplate"] = web_value if isinstance(web_value, list) else []
    elif web_key.startswith("today_extra:"):
        # 临时待办（按日），与今日模板/勾选并列展示
        date = web_key[len("today_extra:"):]
        data.setdefault("todayExtra", {})[date] = web_value if isinstance(web_value, list) else []
    elif web_key == "podcast_list":
        # Web 单集(podcast_list) → PC SharedPodcast(podcasts)，按 src/id 去重合并
        existing = data.get("podcasts") or []
        by_src = {}
        by_id = {}
        for e in existing:
            if isinstance(e, dict):
                if e.get("src"): by_src[e["src"]] = e
                if e.get("id"): by_id[e["id"]] = e
        for it in (web_value or []):
            pc = _web_ep_to_pc(it)
            if pc is None:
                continue
            tgt = by_src.get(pc["src"]) or by_id.get(pc["id"])
            if tgt is None:
                existing.append(pc)
                by_src[pc["src"]] = pc
                by_id[pc["id"]] = pc
            else:
                for k in ("title", "src", "show", "subId", "listened", "plays", "addedAt", "duration"):
                    if pc.get(k) is not None:
                        tgt[k] = pc[k]
        data["podcasts"] = existing
    elif web_key == "notes":
        # 速记：Web 端为完整列表（含 PC 先前拉取的记录 + Web 自身增删），整组替换以支持删除同步
        if isinstance(web_value, list):
            data["notes"] = web_value
    else:
        # 未知 key：忽略（防污染，不再把 Web 私有键原样写进 PC 共享文件）
        pass
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _vault_root() -> Path | None:
    """返回可用的 vault 根目录（Windows 优先，WSL 兜底）"""
    for p in (VAULT_ROOT_WIN, VAULT_ROOT_WSL):
        try:
            if p.exists():
                return p
        except Exception:
            continue
    return None


def load_plugin_settings() -> dict:
    """读取 Obsidian 插件 data.json 中与播客相关的设置"""
    for p in (PLUGIN_DATA_JSON_WIN, PLUGIN_DATA_JSON_WSL):
        try:
            if p.exists():
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return {
                        "podcastDownloadDir": raw.get("podcastDownloadDir") or "10 - Media/播客/下载",
                        "podcastDownloadConfirm": raw.get("podcastDownloadConfirm", True),
                        "habitNoteFolder": raw.get("habitNoteFolder", ""),
                        "unifiedCacheRoot": raw.get("unifiedCacheRoot", ""),
                    }
        except Exception:
            continue
    return {
        "podcastDownloadDir": "10 - Media/播客/下载",
        "podcastDownloadConfirm": True,
        "habitNoteFolder": "",
        "unifiedCacheRoot": "",
    }


def _append_jinju_to_vault(title: str, show: str, text: str) -> str:
    """把 Web 端记的笔记追加到 PC 端「播客金句.md」，与 Obsidian appendJinju 格式一致。"""
    root = _vault_root()
    if root is None:
        raise FileNotFoundError("未找到 vault 根目录")
    cfg = load_plugin_settings()
    folder = (cfg.get("habitNoteFolder") or "").strip() or cfg.get("unifiedCacheRoot") or ""
    base = folder.strip() or "📚 知识库/04 - Archive 归档/工作台缓存"
    target = root / base / "播客金句.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    stamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    block = f"\n## {title}\n- 🕒 {stamp}\n- 📻 {show or '播客单集'}\n\n> {text}\n"
    if target.exists():
        raw = target.read_text(encoding="utf-8")
        target.write_text(raw + block, encoding="utf-8")
    else:
        target.write_text("# 🎧 播客金句\n" + block, encoding="utf-8")
    return str(target)


def _download_audio_to_vault(url: str, name: str | None = None) -> str:
    """下载外链音频到 PC 端 podcastDownloadDir。"""
    root = _vault_root()
    if root is None:
        raise FileNotFoundError("未找到 vault 根目录")
    cfg = load_plugin_settings()
    folder = (cfg.get("podcastDownloadDir") or "").strip() or "10 - Media/播客/下载"
    target_dir = root / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        buf = r.read()
    if not name:
        from urllib.parse import urlparse
        name = pathlib.Path(urlparse(url).path).name or "download.mp3"
    if "." not in name:
        name += ".mp3"
    target = target_dir / name
    target.write_bytes(buf)
    return str(target)


DEFAULT_DASHBOARD_CONFIG = {
    "app": {"title": "然哥个人工作台", "subtitle": "手机端 PWA 个人工作台"},
    "style": {"accent": "#7c6cf0", "accentSoft": "rgba(124,108,240,0.12)", "darkMode": "system"},
    "modules": {
        "today": {"enabled": True, "title": "今日计划"},
        "knowledge": {"enabled": True, "title": "知识库"},
        "news": {"enabled": True, "title": "行业新闻"},
        "podcast": {"enabled": True, "title": "精选播客"},
        "stock": {"enabled": True, "title": "股票池"},
        "topic": {"enabled": True, "title": "选题池"},
        "checkin": {"enabled": True, "title": "每日打卡"},
        "settings": {"enabled": True, "title": "设置"},
    },
    "sources": {},
}


def load_dashboard_config() -> dict:
    """读取 Obsidian 里的《工作台配置.json》，失败时返回默认配置"""
    for p in (DASHBOARD_CONFIG_WSL, DASHBOARD_CONFIG_WIN):
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return DEFAULT_DASHBOARD_CONFIG


def get_tts_mp3(word: str) -> Path:
    """生成（或读取缓存）单词的标准美音 mp3，返回文件路径"""
    import re

    safe = re.sub(r"[^a-zA-Z0-9_'-]", "_", word)[:60]
    out = TTS_CACHE_DIR / f"{safe}.mp3"
    if out.exists() and out.stat().st_size > 100:
        return out
    TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    import asyncio
    import edge_tts

    async def _gen():
        c = edge_tts.Communicate(word, voice=TTS_VOICE, rate="-20%")
        await c.save(str(out))

    asyncio.run(_gen())
    return out

# 前端「刷新」时即时采集：分类 → 采集脚本（脚本输出 stdout JSON list）
COLLECT_SCRIPTS = {
    "politics": "fetch_politics.py",
    "finance": "fetch_finance.py",
    "ai": "fetch_ai_news.py",
}


def collect_feeds(category: str) -> int:
    """调采集脚本 → 解析 stdout JSON → 入库。返回新增条数"""
    import subprocess

    script = Path(__file__).parent.parent / "scripts" / COLLECT_SCRIPTS.get(category, "")
    if not script.exists():
        raise ValueError(f"未知分类或脚本缺失: {category}")

    r = subprocess.run(
        [sys.executable, str(script), "--limit", "10"],
        capture_output=True, text=True, timeout=90,
    )
    if r.returncode != 0:
        raise RuntimeError(f"采集脚本失败: {(r.stderr or '')[:200]}")
    try:
        items = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"采集脚本输出不是 JSON: {e}")
    return append_feeds(items, category=category)

# CORS headers（工作台 PWA fetch 本机端口需要）
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


# ============= 写 review-state.json（原子替换，无丢失窗口）=============
def write_review_state(state: dict) -> None:
    """原子写 review-state.json：先写临时文件，再 rename 替换主文件。
    旧实现先把主文件 rename 成 .bak 再写临时文件 —— 若写临时文件失败，
    主文件已改名、数据"暂时消失"。改为直接 tmp → replace，全程主文件要么是
    旧版要么是新版，不存在中间状态。
    """
    path = pick_review_state_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    # os.replace / Path.replace：原子替换（Windows 上 rename 无法覆盖已存在文件）
    tmp.replace(path)


def mark_card_reviewed(kc_id: str, note: str = "") -> dict:
    """标记某张 KC 复习过 → 写 review-state.json"""
    state = load_review_state()
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()  # 北京时间

    # 更新 lastReviewedAt
    state.setdefault("lastReviewedAt", {})[kc_id] = now
    # 更新 reviewCount
    state.setdefault("reviewCount", {})[kc_id] = state.get("reviewCount", {}).get(kc_id, 0) + 1
    # 追加 history
    state.setdefault("history", []).append({
        "at": now,
        "mode": "manual",
        "action": "card_reviewed",
        "ids": [kc_id],
        "source": "dashboard_workspace",
        "note": note or "从工作台复习入口标记",
    })

    write_review_state(state)
    # 返回推导的新状态
    return derive_card_state(kc_id, state)


# ============= HTTP handler =============
class Handler(BaseHTTPRequestHandler):
    # ========== 投研复盘数据层（模块级函数，GET/POST 共用） ==========
    REVIEW_PATH = Path("/mnt/d/Obsidian Vault/📚 知识库/04 - Archive 归档/工作台缓存/投研数据.json")

    @staticmethod
    def _read_review_db() -> dict:
        try:
            if Handler.REVIEW_PATH.exists():
                raw = json.loads(Handler.REVIEW_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
        except Exception:
            pass
        return {"signals": [], "trades": [], "reviews": []}

    @staticmethod
    def _write_review_db(db: dict) -> None:
        Handler.REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = Handler.REVIEW_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(Handler.REVIEW_PATH)

    # ========== 原有方法 ==========
    def log_message(self, fmt, *args):
        # 静默默认日志，改用 print 简化
        print(f"[{self.log_date_time_string()}] {fmt % args}", flush=True)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, msg, status=400):
        self._send_json({"error": msg}, status)

    def _send_file(self, filepath: Path, mime: str):
        if not filepath.exists() or not filepath.is_file():
            self._send_error_json(f"文件不存在: {filepath.name}", 404)
            return
        body = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # 页面/脚本不缓存，避免手机端拿到旧版本（音频等静态资源不受影响）
        if mime.startswith("text/html") or mime.endswith("javascript"):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """CORS preflight"""
        self.send_response(204)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        qs = parse_qs(url.query)

        try:
            if path == "/api/kc/cards":
                cards = list_cards_with_state()
                self._send_json({"cards": cards, "count": len(cards)})

            elif path == "/api/kc/stats":
                self._send_json(get_stats())

            elif path == "/api/kc/card":
                kc_id = qs.get("id", [""])[0]
                if not kc_id:
                    self._send_error_json("缺少 id 参数")
                    return
                try:
                    self._send_json(read_kc_card_full(kc_id))
                except KeyError as e:
                    self._send_error_json(str(e), 404)

            elif path == "/api/review/today":
                cards = get_today_review()
                self._send_json({"cards": cards, "count": len(cards)})

            elif path == "/api/health":
                self._send_json({"ok": True, "service": "dashboard-backend"})

            elif path == "/api/store":
                # 云同步数据仓库（2026-08-10 打通：读 PC 共享文件并翻译为 Web 命名）
                pc = get_shared_store()
                self._send_json({"ok": True, "data": translate_pc_to_web(pc)})

            elif path == "/api/config":
                # Obsidian 工作台配置（2026-08-06 新增：Obsidian 改配置 → Web 刷新同步）
                self._send_json({"ok": True, "config": load_dashboard_config()})

            elif path == "/api/tts":
                # 标准美音发音（2026-08-06 新增：edge-tts 生成 mp3，手机/电脑发音一致）
                word = qs.get("word", [""])[0].strip()
                if not word:
                    self._send_error_json("缺少 word 参数")
                    return
                try:
                    mp3 = get_tts_mp3(word)
                    self._send_file(mp3, "audio/mpeg")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    self._send_error_json(f"TTS 生成失败: {e}", 500)

            elif path == "/api/feeds/latest":
                category = qs.get("category", [""])[0]
                try:
                    limit = int(qs.get("limit", ["50"])[0])
                    limit = max(1, min(limit, 200))  # 防止 limit=abc 或超大值
                except (ValueError, TypeError):
                    limit = 50
                self._send_json(get_latest_feeds(category=category or None, limit=limit))

            elif path == "/" or path == "/index.html":
                self._send_file(Path(__file__).parent.parent / "index.html", "text/html")

            elif path == "/kpi-v4-preview.html":
                # 2026-08-15：选题池「预览页」tab 嵌入的 Obsidian 工作台 KPI v4 设计稿
                self._send_file(Path(__file__).parent.parent / "kpi-v4-preview.html", "text/html")

            elif path == "/screenshots-viewer.html":
                # 2026-08-15：交互式截图查看器
                self._send_file(Path(__file__).parent.parent / "screenshots-viewer.html", "text/html")

            elif path.startswith("/preview-assets/"):
                # 2026-08-15：预览页截图资源（png/jpg/webp）
                ext = Path(path).suffix.lower()
                mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "application/octet-stream")
                self._send_file(Path(__file__).parent.parent / path.lstrip("/"), mime)

            elif path == "/6charts-current.html":
                # 2026-08-15：6 个图表当前布局预览（仅当文件存在）
                fp = Path(__file__).parent.parent / "6charts-current.html"
                if fp.exists():
                    self._send_file(fp, "text/html")
                else:
                    self._send_error_json(f"未知路径: {path}")

            elif path == "/real-render.html":
                # 2026-08-15：修复版预览
                fp = Path(__file__).parent.parent / "real-render.html"
                if fp.exists():
                    self._send_file(fp, "text/html")
                else:
                    self._send_error_json(f"未知路径: {path}")
            elif path == "/6charts-obsidian.html":
                # 2026-08-15：6 图表 v5 已实装版
                fp = Path(__file__).parent.parent / "6charts-obsidian.html"
                if fp.exists():
                    self._send_file(fp, "text/html")
                else:
                    self._send_error_json(f"未知路径: {path}")
            elif path == "/6charts-v5.html":
                # 2026-08-15：6 个图表 v5 优化设计稿
                fp = Path(__file__).parent.parent / "6charts-v5.html"
                if fp.exists():
                    self._send_file(fp, "text/html")
                else:
                    self._send_error_json(f"未知路径: {path}")

            elif path == "/test_backup.html":
                self._send_file(Path(__file__).parent.parent / "test_backup.html", "text/html")

            elif path == "/review.html" or path == "/review":
                self._send_file(Path(__file__).parent.parent / "review.html", "text/html")

            elif path == "/manifest.json":
                self._send_file(Path(__file__).parent.parent / "manifest.json", "application/json")

            elif path == "/icon.png":
                self._send_file(Path(__file__).parent.parent / "icon.png", "image/png")

            elif path == "/avatar-source.png":
                self._send_file(Path(__file__).parent.parent / "avatar-source.png", "image/png")

            elif path == "/marked.min.js":
                self._send_file(Path(__file__).parent.parent / "marked.min.js", "application/javascript")
            elif path == "/purify.min.js":
                self._send_file(Path(__file__).parent.parent / "purify.min.js", "application/javascript")

            elif path.startswith("/audio/"):
                # 上传的音频直链（2026-08-06 新增：手机/电脑共享同一源）
                fname = path.split("/")[-1]
                if not fname or ".." in fname or "/" in fname:
                    self._send_error_json("非法文件名", 400)
                    return
                ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                mime = {
                    "mp3": "audio/mpeg",
                    "m4a": "audio/mp4",
                    "mp4": "video/mp4",
                    "wav": "audio/wav",
                    "ogg": "audio/ogg",
                }.get(ext, "application/octet-stream")
                self._send_file(Path(__file__).parent / "data" / "audio" / fname, mime)

            # ========== 投研复盘 GET API ==========
            elif path == "/api/review/signals":
                db = Handler._read_review_db()
                sigs = db.get("signals", [])
                src = (qs.get("source", [""])[0] or "").strip()
                sector = (qs.get("sector", [""])[0] or "").strip()
                date_from = (qs.get("date_from", [""])[0] or "").strip()
                date_to = (qs.get("date_to", [""])[0] or "").strip()
                if src:
                    sigs = [s for s in sigs if s.get("source") == src]
                if sector:
                    sigs = [s for s in sigs if s.get("sector") == sector]
                if date_from:
                    sigs = [s for s in sigs if (s.get("date") or "") >= date_from]
                if date_to:
                    sigs = [s for s in sigs if (s.get("date") or "") <= date_to]
                sigs.sort(key=lambda x: x.get("date", ""), reverse=True)
                self._send_json({"ok": True, "signals": sigs, "total": len(sigs)})

            elif path == "/api/review/trades":
                db = Handler._read_review_db()
                trades = db.get("trades", [])
                trades.sort(key=lambda x: x.get("exec_date", ""), reverse=True)
                self._send_json({"ok": True, "trades": trades, "total": len(trades)})

            elif path == "/api/review/stats":
                db = Handler._read_review_db()
                trades = db.get("trades", [])
                if not trades:
                    self._send_json({"ok": True, "stats": None, "message": "暂无交易数据"})
                    return
                wins = [t for t in trades if (t.get("pnl_pct") or 0) > 0]
                losses = [t for t in trades if (t.get("pnl_pct") or 0) <= 0]
                avg_win = sum(t["pnl_pct"] for t in wins) / max(len(wins), 1)
                avg_loss = sum(t["pnl_pct"] for t in losses) / max(len(losses), 1)
                nav = 1.0
                nav_series = {}
                by_date = {}
                for t in trades:
                    d = t.get("exec_date", "")
                    by_date[d] = by_date.get(d, 0) + (t.get("pnl_pct", 0) or 0)
                for d in sorted(by_date.keys()):
                    nav *= 1 + by_date[d]
                    nav_series[d] = round(nav, 4)
                peak = max(nav_series.values()) if nav_series else 1.0
                vals = list(nav_series.values())
                mdd = 0.0
                if vals:
                    idx = vals.index(peak)
                    mdd = round((peak - min(vals[idx:])) / peak, 4) if idx < len(vals) else 0.0
                self._send_json({
                    "ok": True,
                    "stats": {
                        "total_trades": len(trades),
                        "win_count": len(wins),
                        "loss_count": len(losses),
                        "win_rate": round(len(wins) / len(trades) * 100, 1),
                        "avg_win": round(avg_win, 4),
                        "avg_loss": round(avg_loss, 4),
                        "profit_factor": round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 999,
                        "max_dd": round(mdd * 100, 2),
                        "nav": round(nav, 4),
                        "nav_series": nav_series,
                    }
                })

            elif path == "/api/positions/quote":
                # 单只股票实时行情（前端自动补全用）
                try:
                    code = parse_qs(urlparse(self.path).query).get('code', [''])[0].strip()
                    if not code or len(code) != 6 or not code.isdigit():
                        self._send_error_json("code 必须 6 位数字")
                        return
                    prefix = 'sz' if code.startswith(('00','30','15','16','18')) else 'sh'
                    req = urllib.request.Request(
                        f'https://hq.sinajs.cn/list={prefix}{code}',
                        headers={'Referer': 'https://finance.sina.com.cn'}
                    )
                    line = urllib.request.urlopen(req, timeout=8).read().decode('gbk')
                    fields = line.split('"')[1].split(',')
                    price = float(fields[3])
                    prev_close = float(fields[2])
                    today_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0
                    self._send_json({
                        "ok": True,
                        "quote": {
                            "code": code,
                            "name": fields[0],
                            "price": price,
                            "prev_close": prev_close,
                            "today_pct": today_pct,
                            "open": float(fields[1]),
                            "high": float(fields[4]),
                            "low": float(fields[5]),
                        }
                    })
                except Exception as e:
                    self._send_error_json(f"行情拉取失败: {e}", 500)
                return

            elif path == "/api/stock-pool":
                # 股票池：优先读 Obsidian 06 股票池目录下的卡片文件，回退到 review 数据
                pool_root = Path("/mnt/d/Obsidian Vault/🤖 草帽团/04_成长日记/🧭投研复盘/股票池")
                pools = {}
                total = []
                if pool_root.exists():
                    for pool_dir in sorted(pool_root.iterdir()):
                        if not pool_dir.is_dir():
                            continue
                        pool_name = pool_dir.name
                        items = []
                        for md in sorted(pool_dir.glob("*.md")):
                            try:
                                text = md.read_text(encoding="utf-8")
                                item = {"file": md.name, "path": str(md)}
                                for line in text.splitlines():
                                    line = line.strip()
                                    if line.startswith("- **代码**："):
                                        item["code"] = line.replace("- **代码**：", "").strip()
                                    elif line.startswith("- **名称**："):
                                        item["name"] = line.replace("- **名称**：", "").strip()
                                    elif line.startswith("- **赛道**："):
                                        item["sector"] = line.replace("- **赛道**：", "").strip()
                                    elif line.startswith("- **细分**："):
                                        item["sub_sector"] = line.replace("- **细分**：", "").strip()
                                    elif line.startswith("- **星级**："):
                                        item["strength"] = line.replace("- **星级**：", "").strip()
                                    elif line.startswith("- **通过层**："):
                                        item["layers"] = line.replace("- **通过层**：", "").strip()
                                    elif line.startswith("- **当前池**："):
                                        item["current_pool"] = line.replace("- **当前池**：", "").strip()
                                    elif line.startswith("- **录入日期**："):
                                        item["entry_date"] = line.replace("- **录入日期**：", "").strip()
                                    elif line.startswith("- **状态**："):
                                        item["status"] = line.replace("- **状态**：", "").strip()
                                    elif line.startswith("- **催化剂**："):
                                        item["catalyst"] = line.replace("- **催化剂**：", "").strip()
                                    elif line.startswith("- **风险点**："):
                                        item["risk"] = line.replace("- **风险点**：", "").strip()
                                if item.get("code") or item.get("name"):
                                    items.append(item)
                            except Exception:
                                continue
                        pools[pool_name] = items
                        total.extend(items)
                # 兜底：用目录名补 current_pool（防止 Obsidian frontmatter 漏写「当前池」字段）
                for item in total:
                    if not item.get("current_pool"):
                        for pool_name, items in pools.items():
                            if item in items:
                                item["current_pool"] = pool_name
                                break
                # 回退：若 Obsidian 目录为空/不存在，从投研数据.json 的 signals 生成总表
                if not total:
                    db = Handler._read_review_db()
                    sigs = db.get("signals", [])
                    seen = set()
                    for s in sigs:
                        key = s.get("code") or s.get("name") or ""
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        total.append({
                            "code": s.get("code", ""),
                            "name": s.get("name", ""),
                            "sector": s.get("sector", ""),
                            "sub_sector": s.get("sub_sector", ""),
                            "strength": "★" * (s.get("strength") or 1),
                            "current_pool": f"L{s.get('strength',1)}",
                            "entry_date": s.get("date", ""),
                            "status": "跟踪中",
                            "catalyst": s.get("notes", ""),
                            "risk": "",
                            "file": "",
                            "path": "",
                        })
                # 统计
                strength_dist = {}
                sector_dist = {}
                for item in total:
                    st = item.get("strength", "★")
                    strength_dist[st] = strength_dist.get(st, 0) + 1
                    sec = item.get("sector", "其他")
                    sector_dist[sec] = sector_dist.get(sec, 0) + 1
                self._send_json({
                    "ok": True,
                    "pools": pools,
                    "total": total,
                    "count": len(total),
                    "stats": {
                        "strength_dist": strength_dist,
                        "sector_dist": sector_dist,
                        "pool_counts": {k: len(v) for k, v in pools.items()},
                    }
                })

            else:
                self._send_error_json(f"未知路径: {path}", 404)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_error_json(f"server error: {e}", 500)

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/api/positions/from_obsidian":
            # 从 Obsidian current.md 读取当前持仓（web 端启动时拉取对齐）
            try:
                from pathlib import Path as _P
                current_md = _P("/mnt/d/Obsidian Vault/🤖 草帽团/04_成长日记/🧭投研复盘/持仓/current.md")
                if not current_md.exists():
                    self._send_json({"ok": True, "rows": [], "summary": {"count": 0}, "exists": False})
                    return
                txt = current_md.read_text(encoding="utf-8")
                rows: list = []
                if txt.startswith("---\n"):
                    end = txt.index("\n---\n", 4)
                    if end > 0:
                        in_positions = False
                        cur: dict = {}
                        for line in txt[4:end].splitlines():
                            if line.startswith("positions:"):
                                in_positions = True
                                continue
                            if not in_positions:
                                continue
                            m = line.strip()
                            if m.startswith("- code:"):
                                if cur.get("code"):
                                    rows.append(cur)
                                cur = {"code": m.replace("- code:", "").strip()}
                            elif cur and m:
                                kv = m.split(":", 1)
                                if len(kv) == 2:
                                    k, v = kv[0].strip(), kv[1].strip()
                                    if k in ("name", "pool"):
                                        cur[k] = v
                                    elif k in ("qty", "cost", "price", "live_price", "today_pct"):
                                        cur[k] = float(v) or 0
                        if cur.get("code"):
                            rows.append(cur)
                # 派生 pnl_pct / weight / value
                total_value = sum(r.get("live_price", r.get("price", 0)) * r.get("qty", 0) for r in rows)
                for r in rows:
                    cost = r.get("cost", 0)
                    qty = r.get("qty", 0)
                    live = r.get("live_price", r.get("price", 0))
                    r["pnl"] = round((live - cost) * qty, 2)
                    r["pnl_pct"] = round((live - cost) / cost * 100, 2) if cost else 0
                    r["value"] = round(live * qty, 2)
                    r["weight"] = round(r["value"] / total_value * 100, 2) if total_value else 0
                self._send_json({
                    "ok": True,
                    "exists": True,
                    "rows": rows,
                    "summary": {
                        "count": len(rows),
                        "total_value": round(total_value, 2),
                    },
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"读取失败: {e}", 500)
            return

        if path == "/api/positions/parse":
            # 解析同花顺持仓文本 → 结构化 JSON（不写入任何数据库，纯解析）
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
                raw = data.get("text", "")
                rows = []
                for line in raw.splitlines():
                    parts = line.split("\t")
                    if len(parts) < 20:
                        continue
                    if not parts[1].strip().isdigit():
                        continue
                    try:
                        rows.append({
                            "code": parts[2].strip(),
                            "name": parts[3].strip(),
                            "qty": int(parts[6] or 0),
                            "cost": float(parts[10] or 0),
                            "price": float(parts[11] or 0),
                            "pnl": float(parts[5] or 0),
                            "pnl_pct": float(parts[12] or 0),
                            "value": float(parts[14] or 0),
                            "weight": float(parts[15] or 0),
                            "market": parts[18].strip(),
                            "hold_days": int(parts[19] or 0),
                        })
                    except (ValueError, IndexError):
                        continue
                total_value = sum(r["value"] for r in rows)
                total_pnl = sum(r["pnl"] for r in rows)
                self._send_json({
                    "ok": True,
                    "rows": rows,
                    "summary": {
                        "count": len(rows),
                        "total_value": round(total_value, 2),
                        "total_pnl": round(total_pnl, 2),
                        "total_pnl_pct": round(total_pnl / total_value * 100, 2) if total_value else 0,
                    }
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"解析失败: {e}", 500)
            return

        if path == "/api/positions/quote":
            # 单只股票实时行情（前端自动补全用）
            try:
                code = parse_qs(urlparse(self.path).query).get('code', [''])[0].strip()
                if not code or len(code) != 6 or not code.isdigit():
                    self._send_error_json("code 必须 6 位数字")
                    return
                prefix = 'sz' if code.startswith(('00','30','15','16','18')) else 'sh'
                req = urllib.request.Request(
                    f'https://hq.sinajs.cn/list={prefix}{code}',
                    headers={'Referer': 'https://finance.sina.com.cn'}
                )
                line = urllib.request.urlopen(req, timeout=8).read().decode('gbk')
                fields = line.split('"')[1].split(',')
                price = float(fields[3])
                prev_close = float(fields[2])
                today_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0
                self._send_json({
                    "ok": True,
                    "quote": {
                        "code": code,
                        "name": fields[0],
                        "price": price,
                        "prev_close": prev_close,
                        "today_pct": today_pct,
                        "open": float(fields[1]),
                        "high": float(fields[4]),
                        "low": float(fields[5]),
                    }
                })
            except Exception as e:
                self._send_error_json(f"行情拉取失败: {e}", 500)
            return

        if path == "/api/positions/analyze":
            # 持仓策略分析：解析持仓 + 拉实时行情 + 交叉对照池子 + 调 LLM 出策略
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
                # 支持两种输入：1) text 字符串（同花顺粘贴） 2) positions 数组（前端结构化）
                raw = data.get("text", "")
                user_notes = (data.get("notes") or "").strip()
                positions = []
                if data.get("positions") and isinstance(data["positions"], list):
                    # 前端结构化输入
                    for p in data["positions"]:
                        try:
                            positions.append({
                                "code": str(p["code"]).strip(),
                                "name": str(p.get("name", "")).strip(),
                                "qty": int(p.get("qty") or 0),
                                "cost": float(p.get("cost") or 0),
                                "price": float(p.get("price") or 0),
                                "hold_days": int(p.get("hold_days") or 0),
                            })
                        except (ValueError, TypeError, KeyError):
                            continue
                elif raw:
                    # 兼容旧 text 路径
                    for line in raw.splitlines():
                        parts = line.split("\t")
                        if len(parts) < 20 or not parts[1].strip().isdigit():
                            continue
                        try:
                            positions.append({
                                "code": parts[2].strip(),
                                "name": parts[3].strip(),
                                "qty": int(parts[6] or 0),
                                "cost": float(parts[10] or 0),
                                "price": float(parts[11] or 0),
                                "pnl": float(parts[5] or 0),
                                "pnl_pct": float(parts[12] or 0),
                                "value": float(parts[14] or 0),
                                "weight": float(parts[15] or 0),
                                "hold_days": int(parts[19] or 0),
                            })
                        except (ValueError, IndexError):
                            continue
                if not positions:
                    self._send_error_json("未识别到持仓数据")
                    return
                # 2) 批量拉实时行情（新浪 hq.sinajs.cn 一次批量）
                def _code_prefix(c):
                    return ('sz' if c.startswith(('00','30','15','16','18')) else 'sh') + c
                codes_str = ','.join(_code_prefix(p['code']) for p in positions)
                quote_map = {}
                try:
                    req = urllib.request.Request(
                        f'https://hq.sinajs.cn/list={codes_str}',
                        headers={'Referer': 'https://finance.sina.com.cn'}
                    )
                    lines = urllib.request.urlopen(req, timeout=10).read().decode('gbk').splitlines()
                    for line in lines:
                        m = line.split('"')
                        if len(m) < 2:
                            continue
                        fields = m[1].split(',')
                        qcode = line.split('hq_str_')[1].split('=')[0]
                        code = qcode[2:]
                        quote_map[code] = {
                            'open': float(fields[1]),
                            'prev_close': float(fields[2]),
                            'price': float(fields[3]),
                            'high': float(fields[4]),
                            'low': float(fields[5]),
                            'volume': int(fields[8]) if fields[8] else 0,
                            'amount': float(fields[9]) if fields[9] else 0,
                        }
                except Exception as e:
                    self._send_error_json(f"实时行情拉取失败: {e}", 500)
                    return
                # 3) 实时行情注入到每条持仓 + 派生 pnl_pct / weight
                total_value = 0
                for p in positions:
                    q = quote_map.get(p['code'], {})
                    p['live_price'] = q.get('price', p['price'])
                    p['open'] = q.get('open', 0)
                    p['high'] = q.get('high', 0)
                    p['low'] = q.get('low', 0)
                    p['prev_close'] = q.get('prev_close', 0)
                    if q.get('prev_close'):
                        p['today_pct'] = round((q['price'] - q['prev_close']) / q['prev_close'] * 100, 2)
                    else:
                        p['today_pct'] = 0
                    # 派生字段（前端 positions 数组输入路径没传）
                    cost = p.get('cost', 0)
                    qty = p.get('qty', 0)
                    p['pnl'] = round((p['live_price'] - cost) * qty, 2) if cost else 0
                    p['pnl_pct'] = round((p['live_price'] - cost) / cost * 100, 2) if cost else 0
                    p['value'] = round(p['live_price'] * qty, 2)
                    total_value += p['value']
                # 仓位占比（基于总市值）
                for p in positions:
                    p['weight'] = round(p['value'] / total_value * 100, 2) if total_value else 0
                # 4) 拉 L1-L5 池子完整档案（code → 池子 + 星级 + 催化剂 + 风险点 + 赛道）
                pool_root = Path("/mnt/d/Obsidian Vault/🤖 草帽团/04_成长日记/🧭投研复盘/股票池")
                pool_map = {}  # code → 池子名
                pool_full = {}  # code → {sector, sub_sector, strength, catalyst, risk, status, entry_date}
                if pool_root.exists():
                    for d in pool_root.iterdir():
                        if not d.is_dir():
                            continue
                        for md in d.glob("*.md"):
                            try:
                                txt = md.read_text(encoding="utf-8", errors="ignore")
                            except Exception:
                                continue
                            item = {"pool": d.name}
                            # 解析 frontmatter
                            if txt.startswith("---\n"):
                                end = txt.find("\n---\n", 4)
                                if end > 0:
                                    for line in txt[4:end].splitlines():
                                        if ":" in line:
                                            k, v = line.split(":", 1)
                                            item[k.strip()] = v.strip()
                            # 解析正文字段
                            for line in txt.splitlines():
                                s = line.strip()
                                if s.startswith("- **代码**：") and not item.get("code"):
                                    item["code"] = s.replace("- **代码**：", "").strip()
                                elif s.startswith("- **名称**：") and not item.get("name"):
                                    item["name"] = s.replace("- **名称**：", "").strip()
                                elif s.startswith("- **赛道**：") and not item.get("sector"):
                                    item["sector"] = s.replace("- **赛道**：", "").strip()
                                elif s.startswith("- **细分**：") and not item.get("sub_sector"):
                                    item["sub_sector"] = s.replace("- **细分**：", "").strip()
                                elif s.startswith("- **星级**：") and not item.get("strength"):
                                    item["strength"] = s.replace("- **星级**：", "").strip()
                                elif s.startswith("- **催化剂**：") and not item.get("catalyst"):
                                    item["catalyst"] = s.replace("- **催化剂**：", "").strip()
                                elif s.startswith("- **风险点**：") and not item.get("risk"):
                                    item["risk"] = s.replace("- **风险点**：", "").strip()
                                elif s.startswith("- **状态**：") and not item.get("status"):
                                    item["status"] = s.replace("- **状态**：", "").strip()
                                elif s.startswith("- **录入日期**：") and not item.get("entry_date"):
                                    item["entry_date"] = s.replace("- **录入日期**：", "").strip()
                            code = item.get("code", "")
                            if code:
                                pool_map[code] = d.name
                                pool_full[code] = item
                for p in positions:
                    p["pool"] = pool_map.get(p["code"], "不在池子")
                    # 把池子里的催化剂/风险点也挂到持仓上
                    pf = pool_full.get(p["code"], {})
                    p["pool_catalyst"] = pf.get("catalyst", "")
                    p["pool_risk"] = pf.get("risk", "")
                    p["pool_strength"] = pf.get("strength", "")
                    p["pool_sector"] = pf.get("sector", "")
                # 5) 拉历史 signals（投研数据.json）
                signals_by_code = {}  # code → [最近N条信号]
                try:
                    db = Handler._read_review_db()
                    for sig in db.get("signals", []):
                        code = (sig.get("code") or "").strip()
                        if code and len(code) == 6:
                            signals_by_code.setdefault(code, []).append({
                                "date": sig.get("date", ""),
                                "direction": sig.get("direction") or sig.get("dir", ""),
                                "strength": sig.get("strength", 0),
                                "sector": sig.get("sector", ""),
                                "notes": sig.get("notes", ""),
                            })
                    # 每个 code 只取最近 5 条
                    for code in signals_by_code:
                        signals_by_code[code] = signals_by_code[code][-5:]
                except Exception:
                    pass
                for p in positions:
                    p["recent_signals"] = signals_by_code.get(p["code"], [])
                # 6) 大盘指数实时行情（上证/深证/创业板/科创板）
                market_indices = []
                try:
                    market_req = urllib.request.Request(
                        "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000688",
                        headers={"Referer": "https://finance.sina.com.cn"}
                    )
                    lines = urllib.request.urlopen(market_req, timeout=8).read().decode("gbk").splitlines()
                    for line in lines:
                        parts = line.split('"')
                        if len(parts) < 2:
                            continue
                        fields = parts[1].split(",")
                        sym = line.split("hq_str_")[1].split("=")[0]
                        name_map = {"sh000001": "上证", "sz399001": "深证", "sz399006": "创业板", "sh000688": "科创板"}
                        price = float(fields[3])
                        prev = float(fields[2])
                        pct = round((price - prev) / prev * 100, 2) if prev else 0
                        market_indices.append({
                            "name": name_map.get(sym, sym),
                            "price": price,
                            "today_pct": pct,
                        })
                except Exception:
                    pass
                # 7) 组装 LLM prompt
                pos_lines = []
                for p in positions:
                    sig_text = ""
                    if p["recent_signals"]:
                        sigs = " / ".join(
                            f"{s['date']} {s['direction']}{s['strength']}★ {s['sector']}"
                            for s in p["recent_signals"][-3:]
                        )
                        sig_text = f" | 最近信号: {sigs}"
                    pool_remark = ""
                    if p["pool"] != "不在池子":
                        remarks = []
                        if p["pool_strength"]: remarks.append(f"评级 {p['pool_strength']}")
                        if p["pool_sector"]: remarks.append(f"赛道 {p['pool_sector']}")
                        if p["pool_catalyst"] and p["pool_catalyst"] != "-": remarks.append(f"催化「{p['pool_catalyst']}」")
                        if p["pool_risk"] and p["pool_risk"] != "-": remarks.append(f"风险「{p['pool_risk']}」")
                        if remarks:
                            pool_remark = f" | 档案: " + " | ".join(remarks)
                    pos_lines.append(
                        f"- {p['code']} {p['name']} | 持仓{p['qty']}股 | 成本{p['cost']:.3f} | "
                        f"现价{p['live_price']:.3f} | 当日{p['today_pct']:+.2f}% | "
                        f"浮亏率{p['pnl_pct']:+.2f}% | 仓位{p['weight']:.2f}% | "
                        f"持股{p['hold_days']}天 | 池子:{p['pool']}{pool_remark}{sig_text}"
                    )
                positions_block = '\n'.join(pos_lines)
                # 池子候选（持有用户研究过但没买的）
                candidates = [f"{c} {pool_full[c].get('name','')} ({pool_full[c].get('strength','')}) - 催化「{pool_full[c].get('catalyst','-')}」"
                              for c in pool_map if c not in {pp['code'] for pp in positions}]
                pool_lines = '\n'.join(f"- {n}" for n in candidates[:25]) or '（无）'
                # 持仓里没池子背书的
                no_pool = [p for p in positions if p['pool'] == '不在池子']
                nopool_lines = '\n'.join(
                    f"- {p['code']} {p['name']} ({p['pnl_pct']:+.1f}%, 持仓{p['hold_days']}天)"
                    for p in no_pool
                ) or '（无）'
                # 大盘环境
                market_lines = '\n'.join(
                    f"- {m['name']}: {m['price']:.2f} ({m['today_pct']:+.2f}%)"
                    for m in market_indices
                ) or '（行情拉取失败）'
                user_notes_block = f"\n\n## 用户备注\n{user_notes}" if user_notes else ""
                prompt = f"""你是一位专业 A 股投研分析师。基于以下完整数据，给出可执行的下一步交易策略。

## 大盘环境（今日实时）
{market_lines}

## 用户当前持仓（含实时行情 + 池子档案 + 历史信号）
{positions_block}

## 用户研究池子里看好但没买的标的（含评级 + 催化剂）
{pool_lines}

## 用户持仓里不在任何研究池子的标的（没被研究背书）
{nopool_lines}{user_notes_block}

## 分析判断准则（按优先级使用）

### A. 组合层（看大盘 + 整体仓位）
1. 大盘是涨/跌/震荡 → 决定加仓节奏（涨不追高、跌不抄底、震荡做 T）
2. 整体浮亏率 / 现金比例 → 决定止损宽松度

### B. 单只层（看实时行情 + 历史信号 + 池子档案）
1. **实时行情**：当日 >+5% 或 <-5% = 异常波动，需要警惕
2. **历史信号**：用户在 signals 里给过什么评级/方向？强度趋势是升级还是降级？
3. **池子档案**：用户的星级 / 催化剂 / 风险点 是怎么写的？这代表用户自己的研究判断
4. **池子归属**：在 L1/L2 = 强研究背书；L3 = 备选观察；L4/L5 = 重点或执行；不在池子 = 没研究过
5. **持仓天数 + 浮亏率**：>180 天 + <-30% = 深度套牢，必须讨论止损；<60 天 + 浮亏 = 正常波动

### C. 调仓方向
- 池子里有、持仓里没 → 评估是否换股加仓
- 持仓里有、池子里没 → 评估是否止损换出
- 持仓 + 池子都在 → 是否加仓或减仓（看催化剂 + 风险点）

## 输出结构（markdown 表格必须用 GFM 格式：`| 列1 | 列2 |`，下方跟 `|---|---|`）

### 1. 大盘与仓位总览
2-3 句话点明当下大盘状态 + 你的组合状态

### 2. 健康度检查（markdown 表格，5-10 行）
| # | 预警项 | 严重度 | 关键数字 | 依据 |
|---|---|---|---|---|

### 3. 调仓换股建议
**建议加仓**：哪些标的（含理由 + 价位 + 仓位比例）
**建议减仓 / 止损**：哪些需要减仓（含止损价位 / 仓位比例）
**建议换股**：具体替换关系（A → B，理由）

### 4. 单股策略（每只 3 行）
代码 名称 — 当前判断（多/空/中性）+ 关键价位 + 操作建议（持有/加仓/减仓/止损）

### 5. 整体仓位策略
- 总仓位加减方向
- 板块轮动建议
- 接下来一周优先级动作（Top 3）

要求：中文、结论先行、数字说话、依据透明。"""
                # 6) 调 LLM
                api_key = os.environ.get('MINIMAX_API_KEY') or ''
                if not api_key:
                    from pathlib import Path as P
                    env_path = P.home() / '.hermes' / '.env'
                    if env_path.exists():
                        for line in env_path.read_text().splitlines():
                            if line.startswith('MINIMAX_API_KEY='):
                                api_key = line.split('=', 1)[1].strip()
                                break
                if not api_key:
                    self._send_error_json("MINIMAX_API_KEY 未配置", 500)
                    return
                llm_payload = {
                    'model': 'MiniMax-M3',
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': 4096,
                    'temperature': 0.5,
                }
                req = urllib.request.Request(
                    'https://api.minimaxi.com/v1/text/chatcompletion_v2',
                    data=json.dumps(llm_payload).encode('utf-8'),
                    headers={
                        'Authorization': 'Bearer ' + api_key,
                        'Content-Type': 'application/json',
                    },
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=120) as r:
                    llm_resp = json.loads(r.read().decode('utf-8'))
                llm_text = llm_resp['choices'][0]['message']['content']
                self._send_json({
                    'ok': True,
                    'positions': positions,
                    'summary': {
                        'count': len(positions),
                        'total_value': round(sum(p['value'] for p in positions), 2),
                        'total_pnl': round(sum(p['pnl'] for p in positions), 2),
                    },
                    'pool_map': pool_map,
                    'analysis': llm_text,
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"分析失败: {e}", 500)
            return

        if path == "/api/positions/save_report":
            # 把分析报告导出到 Obsidian「🧭投研复盘」目录
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
                analysis = (data.get("analysis") or "").strip()
                positions = data.get("positions") or []
                notes = (data.get("notes") or "").strip()
                if not analysis:
                    self._send_error_json("报告内容为空")
                    return
                # 目标目录：与 Obsidian 工作台 stocks-hub.ts:25 REPORTS_DIR 对齐
                # 修复历史：原本写到 04_成长日记/🧭投研复盘/ 根目录，导致工作台复盘页永远空
                target_dir = Path("/mnt/d/Obsidian Vault/🤖 草帽团/04_成长日记/🧭投研复盘/持仓/reports")
                target_dir.mkdir(parents=True, exist_ok=True)
                # 文件名
                from datetime import datetime as _dt
                now = _dt.now()
                filename = f"持仓策略分析_{now.strftime('%Y-%m-%d_%H%M')}.md"
                # 拼装 markdown
                total_value = sum(p.get('value', 0) for p in positions)
                total_cost = sum(p.get('cost', 0) * p.get('qty', 0) for p in positions)
                total_pnl = total_value - total_cost
                pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
                pnl_sign = '+' if total_pnl >= 0 else ''
                # 持仓快照表
                pos_table_lines = [
                    "| 代码 | 名称 | 持仓 | 成本 | 现价 | 当日% | 浮盈亏率 | 仓位% | 持股天 | 池子 |",
                    "|---|---|---|---|---|---|---|---|---|---|",
                ]
                for p in positions:
                    today_pct = p.get('today_pct', 0)
                    pnl_pct_p = p.get('pnl_pct', 0)
                    pos_table_lines.append(
                        f"| {p.get('code','')} | {p.get('name','')} | {p.get('qty',0)} | "
                        f"{p.get('cost',0):.3f} | {p.get('live_price', p.get('price',0)):.3f} | "
                        f"{today_pct:+.2f}% | {pnl_pct_p:+.2f}% | {p.get('weight',0):.2f}% | "
                        f"{p.get('hold_days',0)} | {p.get('pool','不在池子')} |"
                    )
                pos_table = '\n'.join(pos_table_lines)
                notes_block = f"\n## 用户备注\n\n{notes}\n" if notes else ""
                content = f"""# 持仓策略分析 · {now.strftime('%Y-%m-%d %H:%M')}

> **来源**：web 工作台 · 持仓策略分析
> **持仓数**：{len(positions)} 只
> **总市值**：{total_value:,.2f} 元
> **总成本**：{total_cost:,.2f} 元
> **浮动盈亏**：{pnl_sign}{total_pnl:,.2f} 元（{pnl_sign}{pnl_pct:.2f}%）

## 持仓快照

{pos_table}{notes_block}

## LLM 策略分析

{analysis}

---
*本报告由 web 工作台自动生成 · MiniMax-M3 · 数据源：同花顺持仓 / 新浪实时行情 / L1-L5 股票池档案 / 历史 signals*
"""
                # 写文件
                filepath = target_dir / filename
                filepath.write_text(content, encoding='utf-8')
                self._send_json({
                    'ok': True,
                    'path': str(filepath).replace('\\', '/'),
                    'filename': filename,
                    'url': 'obsidian://open?path=' + str(filepath).replace('\\', '/'),
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"导出失败: {e}", 500)
            return

        if path == "/api/podcast/note":
            # Web 端记笔记 → 追加到 PC 端「播客金句.md」 + 更新 PC 共享数据 noteCount
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
                title = data.get("title", "未命名单集")
                show = data.get("show", "")
                text = (data.get("text") or "").strip()
                ep_id = data.get("id")
                if not text:
                    self._send_error_json("笔记内容不能为空")
                    return
                file_path = _append_jinju_to_vault(title, show, text)
                # 更新 PC 共享数据 noteCount
                if ep_id:
                    try:
                        pcdata = get_shared_store()
                        podcasts = pcdata.get("podcasts") or []
                        updated = False
                        for ep in podcasts:
                            if isinstance(ep, dict) and ep.get("id") == ep_id:
                                ep["noteCount"] = (ep.get("noteCount") or 0) + 1
                                updated = True
                                break
                        if updated:
                            put_shared_key("podcasts", podcasts)
                    except Exception:
                        pass
                self._send_json({"ok": True, "path": file_path.replace("\\", "/")})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"记笔记失败: {e}", 500)
            return

        if path == "/api/podcast/download":
            # Web 端下载当前播放音频到 PC 端 podcastDownloadDir
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
                url = (data.get("url") or "").strip()
                name = (data.get("name") or "").strip()
                if not url:
                    self._send_error_json("缺少下载 URL")
                    return
                if not (url.startswith("http://") or url.startswith("https://")):
                    self._send_error_json("仅支持 http/https 外链下载")
                    return
                file_path = _download_audio_to_vault(url, name)
                self._send_json({"ok": True, "path": file_path.replace("\\", "/")})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"下载失败: {e}", 500)
            return

        if path == "/api/audio/upload":
            # 上传音频文件（2026-08-06 新增：手机/电脑共享同一源）
            # 前端以原始二进制 body 上传，文件名在 ?name=xxx.mp3
            try:
                import uuid as _uuid
                from urllib.parse import parse_qs as _parse_qs
                qs = _parse_qs(url.query)
                fname = (qs.get("name", [""])[0] or "").strip()
                if not fname or "/" in fname or "\\" in fname or ".." in fname:
                    self._send_error_json("缺少或非法的文件名参数 name")
                    return
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > 200 * 1024 * 1024:  # 上限 200MB
                    self._send_error_json("文件为空或超过 200MB 限制")
                    return
                raw = self.rfile.read(length)
                audio_dir = Path(__file__).parent / "data" / "audio"
                audio_dir.mkdir(parents=True, exist_ok=True)
                ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "mp3"
                if ext not in ("mp3", "m4a", "mp4", "wav", "ogg"):
                    self._send_error_json(f"不支持的文件类型: {ext}")
                    return
                safe = _uuid.uuid4().hex[:10] + "." + ext
                (audio_dir / safe).write_bytes(raw)
                self._send_json({"ok": True, "url": "/audio/" + safe, "size": length})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"上传失败: {e}", 500)
            return

        if path not in ("/api/review/mark", "/api/review/add_signal", "/api/review/add_trade", "/api/feeds/push", "/api/feeds/collect", "/api/store"):
            self._send_error_json(f"未知 POST 路径: {path}", 404)
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_error_json("body 不是合法 JSON")
            return

        if path == "/api/review/mark":
            kc_id = data.get("id")
            if not kc_id:
                self._send_error_json("缺少 id")
                return
            note = data.get("note", "")
            try:
                new_state = mark_card_reviewed(kc_id, note)
                self._send_json({"ok": True, "id": kc_id, "review": new_state})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"写入失败: {e}", 500)
            return

        if path == "/api/feeds/push":
            items = data.get("items") or []
            category = data.get("category", "ai")
            if not isinstance(items, list):
                self._send_error_json("items 必须是数组")
                return
            try:
                count = append_feeds(items, category=category)
                self._send_json({"ok": True, "category": category, "count": count})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"推送失败: {e}", 500)
            return

        if path == "/api/feeds/collect":
            # 前端点「刷新」→ 即时跑一次采集脚本 → 入库（可能耗时几秒~几十秒）
            category = data.get("category", "")
            if category not in COLLECT_SCRIPTS:
                self._send_error_json("分类必须是 politics / finance / ai")
                return
            try:
                added = collect_feeds(category)
                self._send_json({"ok": True, "category": category, "added": added})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"采集失败: {e}", 500)
            return

        if path == "/api/store":
            # 云同步写入（2026-08-10 打通：Web 命名 → PC 命名后原子合并）
            # 单 key：{key, value}；批量：{data: {...}}（首次迁移）
            try:
                if "data" in data and isinstance(data["data"], dict):
                    for k, v in data["data"].items():
                        merge_web_to_pc(k, v)
                    self._send_json({"ok": True, "mode": "batch", "count": len(data["data"])})
                elif data.get("key"):
                    merge_web_to_pc(str(data["key"]), data.get("value"))
                    self._send_json({"ok": True, "mode": "single", "key": data["key"]})
                else:
                    self._send_error_json("需要 {key,value} 或 {data:{...}}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error_json(f"store 写入失败: {e}", 500)
            return

        if path == "/api/review/signals":
            db = Handler._read_review_db()
            sigs = db.get("signals", [])
            # 支持按 source/sector/date 过滤
            src = (data.get("source") or "").strip() if isinstance(data, dict) else ""
            sector = (data.get("sector") or "").strip() if isinstance(data, dict) else ""
            date_from = (data.get("date_from") or "").strip() if isinstance(data, dict) else ""
            date_to = (data.get("date_to") or "").strip() if isinstance(data, dict) else ""
            if src:
                sigs = [s for s in sigs if s.get("source") == src]
            if sector:
                sigs = [s for s in sigs if s.get("sector") == sector]
            if date_from:
                sigs = [s for s in sigs if (s.get("date") or "") >= date_from]
            if date_to:
                sigs = [s for s in sigs if (s.get("date") or "") <= date_to]
            sigs.sort(key=lambda x: x.get("date", ""), reverse=True)
            self._send_json({"ok": True, "signals": sigs, "total": len(sigs)})
            return

        if path == "/api/review/trades":
            db = Handler._read_review_db()
            trades = db.get("trades", [])
            trades.sort(key=lambda x: x.get("exec_date", ""), reverse=True)
            self._send_json({"ok": True, "trades": trades, "total": len(trades)})
            return

        if path == "/api/review/stats":
            db = Handler._read_review_db()
            trades = db.get("trades", [])
            if not trades:
                self._send_json({"ok": True, "stats": None, "message": "暂无交易数据"})
                return
            wins = [t for t in trades if (t.get("pnl_pct") or 0) > 0]
            losses = [t for t in trades if (t.get("pnl_pct") or 0) <= 0]
            avg_win = sum(t["pnl_pct"] for t in wins) / max(len(wins), 1)
            avg_loss = sum(t["pnl_pct"] for t in losses) / max(len(losses), 1)
            nav = 1.0
            nav_series = {}
            by_date = {}
            for t in trades:
                d = t.get("exec_date", "")
                by_date[d] = by_date.get(d, 0) + (t.get("pnl_pct", 0) or 0)
            for d in sorted(by_date.keys()):
                nav *= 1 + by_date[d]
                nav_series[d] = round(nav, 4)
            peak = max(nav_series.values()) if nav_series else 1.0
            vals = list(nav_series.values())
            mdd = 0.0
            if vals:
                idx = vals.index(peak)
                mdd = round((peak - min(vals[idx:])) / peak, 4) if idx < len(vals) else 0.0
            self._send_json({
                "ok": True,
                "stats": {
                    "total_trades": len(trades),
                    "win_count": len(wins),
                    "loss_count": len(losses),
                    "win_rate": round(len(wins) / len(trades) * 100, 1),
                    "avg_win": round(avg_win, 4),
                    "avg_loss": round(avg_loss, 4),
                    "profit_factor": round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 999,
                    "max_dd": round(mdd * 100, 2),
                    "nav": round(nav, 4),
                    "nav_series": nav_series,
                }
            })
            return

        if path == "/api/review/add_signal":
            if not isinstance(data, dict) or not data.get("date"):
                self._send_error_json("缺少 date"); return
            db = Handler._read_review_db()
            sig = {
                "id": data.get("id") or ("sig_" + uuid.uuid4().hex[:10]),
                "date": str(data["date"]),
                "source": str(data.get("source", "manual")),
                "source_ref": str(data.get("source_ref", "")),
                "code": str(data.get("code", "")),
                "name": str(data.get("name", "")),
                "sector": str(data.get("sector", "")),
                "sub_sector": str(data.get("sub_sector", "")),
                "signal_type": str(data.get("signal_type", "")),
                "direction": str(data.get("direction", "")),
                "strength": int(data.get("strength", 3)),
                "tags": data.get("tags") or [],
                "notes": str(data.get("notes", "")),
                "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            }
            db.setdefault("signals", []).append(sig)
            Handler._write_review_db(db)
            self._send_json({"ok": True, "signal": sig})
            return

        if path == "/api/review/add_trade":
            if not isinstance(data, dict) or not data.get("exec_date"):
                self._send_error_json("缺少 exec_date"); return
            db = Handler._read_review_db()
            trade = {
                "id": data.get("id") or ("trade_" + uuid.uuid4().hex[:10]),
                "exec_date": str(data["exec_date"]),
                "code": str(data.get("code", "")),
                "name": str(data.get("name", "")),
                "sector": str(data.get("sector", "")),
                "direction": str(data.get("direction", "long")),
                "volume": data.get("volume"),
                "entry_price": data.get("entry_price"),
                "exit_price": data.get("exit_price"),
                "exit_date": str(data.get("exit_date", "")),
                "pnl_pct": data.get("pnl_pct"),
                "pnl_abs": data.get("pnl_abs"),
                "hold_days": data.get("hold_days"),
                "exit_reason": str(data.get("exit_reason", "")),
                "reasoning": str(data.get("reasoning", "")),
                "timeframe": str(data.get("timeframe", "mid")),
                "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            }
            db.setdefault("trades", []).append(trade)
            Handler._write_review_db(db)
            self._send_json({"ok": True, "trade": trade})
            return


def main():
    # pythonw.exe 无控制台时 stdout/stderr 为 None，重定向到 server.log，避免 print 崩溃
    if sys.stdout is None or sys.stderr is None:
        log_path = Path(__file__).with_name("server.log")
        log_f = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_f
        sys.stderr = log_f
    print(f"🚀 工作台后端服务启动")
    print(f"   监听: http://0.0.0.0:{PORT}")
    print(f"   本机: http://127.0.0.1:{PORT}/api/health")
    print(f"   Tailscale: http://<你的 Tailscale IP>:{PORT}/api/health")
    print(f"   Ctrl+C 停止")
    print()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 服务停止")
        server.server_close()


if __name__ == "__main__":
    main()