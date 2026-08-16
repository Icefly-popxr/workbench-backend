#!/usr/bin/env python3
"""
KC 卡片扫描器 · 只读 · 工作台后端用
扫描 D:\\Obsidian Vault\\📚 知识库\\02 - Areas 领域\\ 和 05 - Wikis\\ 下所有 KC-*.md
解析 frontmatter + 正文，返回结构化数据
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

# ============= 路径配置（按然哥实际环境）=============
# WSL 路径（脚本跑在 WSL 时）
WSL_KB_ROOT = Path("/mnt/d/Obsidian Vault/📚 知识库")
# Windows 路径（备用，scripts/ 真在 Windows 跑也用得到）
WIN_KB_ROOT = Path("D:/Obsidian Vault/📚 知识库")

# KC 卡片所在的子目录（按 mingxin-review 的扫描规则）
KC_SEARCH_DIRS = ["02 - Areas 领域", "05 - Wikis 概念库"]


def pick_kb_root() -> Path:
    """探测 WSL / Windows 用哪条路径"""
    if WSL_KB_ROOT.exists():
        return WSL_KB_ROOT
    if WIN_KB_ROOT.exists():
        return WIN_KB_ROOT
    raise FileNotFoundError(f"找不到知识库根目录: {WSL_KB_ROOT} 或 {WIN_KB_ROOT}")


# ============= frontmatter 解析（轻量级，不依赖 pyyaml）=============
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 markdown frontmatter + 正文。返回 (meta_dict, body)"""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta_text, body = m.group(1), m.group(2)
    meta = {}
    # 简单解析 tags: [a, b] / key: value / key: "value"
    for line in meta_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        # tags: [a, b, c]
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1]
            meta[k] = [x.strip().strip('"\'') for x in inner.split(",") if x.strip()]
        else:
            # 去引号
            meta[k] = v.strip('"\'')
    return meta, body


# ============= KC 卡片提取 =============
KC_FILE_RE = re.compile(r"^KC-(.+)\.md$")


def extract_kc_id_from_filename(filename: str) -> Optional[str]:
    """从文件名 KC-{分类}-{编号}-{标题}.md 提取 id"""
    m = KC_FILE_RE.match(filename)
    if not m:
        return None
    # 文件名里的第一段可能是分类，但我们以 frontmatter.id 为准
    return None


def scan_kc_cards(kb_root: Path = None) -> list[dict]:
    """扫描知识库，返回所有 KC 卡片的结构化数据"""
    kb_root = kb_root or pick_kb_root()
    cards = []
    for subdir in KC_SEARCH_DIRS:
        dir_path = kb_root / subdir
        if not dir_path.exists():
            continue
        # 递归找所有 KC-*.md
        # 过滤备份目录（_bak- / .bak- / .backup / _old 等）
        for fpath in dir_path.rglob("KC-*.md"):
            # 跳过备份目录里的卡（任何路径段以 _bak-/.bak-/_backup/_old 开头）
            path_parts = fpath.parts
            if any(p.startswith(('_bak-', '.bak-', '_backup', '_old')) for p in path_parts):
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
            except Exception:
                continue
            meta, body = parse_frontmatter(text)
            # 必须有 id 字段
            kc_id = meta.get("id")
            if not kc_id:
                # 退化：用文件名
                kc_id = fpath.stem
            # 标题：正文第一行 # 开头
            title_match = re.search(r"^#\s+(.+)$", body.strip(), re.MULTILINE)
            title = title_match.group(1).strip() if title_match else kc_id
            # 分类：从相对路径提取（02 - Areas 领域/认知管理/KC-...md → 认知管理）
            rel = fpath.relative_to(dir_path)
            category = rel.parts[0] if len(rel.parts) > 1 else subdir
            cards.append({
                "id": kc_id,
                "title": title,
                "category": category,
                "type": meta.get("type", ""),
                "level": meta.get("level", ""),
                "gates": meta.get("gates", ""),
                "tags": meta.get("tags", []),
                "created": meta.get("created", ""),
                "updated": meta.get("updated", ""),
                "path": str(fpath),  # WSL 或 Windows 路径
                "body_preview": body[:200].strip().replace("\n", " "),
            })
    # 按 created 倒序（新卡在前）
    cards.sort(key=lambda c: c.get("created", "") or "", reverse=True)
    return cards


# ============= review-state.json 读取 =============
# 2026-08-16 改造 · 与 PC 端统一到 vault 工作台缓存目录（之前散落在 00_工具/）
REVIEW_STATE_PATH_WSL = Path("/mnt/d/Obsidian Vault/📚 知识库/04 - Archive 归档/工作台缓存/review-state.json")
REVIEW_STATE_PATH_WIN = Path("D:/Obsidian Vault/📚 知识库/04 - Archive 归档/工作台缓存/review-state.json")


def pick_review_state_path() -> Path:
    for p in [REVIEW_STATE_PATH_WSL, REVIEW_STATE_PATH_WIN]:
        if p.exists():
            return p
    raise FileNotFoundError("找不到 review-state.json")


def load_review_state() -> dict:
    """读 review-state.json，损坏时按 mingxin-review skill 的修复建议处理"""
    path = pick_review_state_path()
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        # 按 mingxin-review SKILL.md 的坑 2：JSON 损坏 → 输出"共 0 张"
        # 但工作台要提示用户，不是静默吞
        raise RuntimeError(
            f"review-state.json 解析失败: {e}. "
            f"请检查是否有未转义的引号（参考 mingxin-review SKILL.md 坑 2）"
        )


# ============= mingxin 状态机推导 =============
def derive_card_state(kc_id: str, review_state: dict) -> dict:
    """按 mingxin 状态机推导单张卡的复习状态"""
    last_reviewed = review_state.get("lastReviewedAt", {}).get(kc_id)
    review_count = review_state.get("reviewCount", {}).get(kc_id, 0)

    if last_reviewed is None:
        # 没复习过 → learning（新卡，3 天后首次复习）
        return {
            "state": "learning",
            "correctStreak": 0,
            "reviewCount": 0,
            "nextReviewAt": None,
            "lastReviewedAt": None,
        }

    # 复习过 → 按 streak 推状态
    # 简化：reviewCount 0 = learning / 1 = stable / >=2 = mastered
    # 实际 mingxin 用 nextIntervalDays，下次复习时间存在 lastReviewedAt
    from datetime import datetime, timezone, timedelta

    last_dt = datetime.fromisoformat(last_reviewed)
    now = datetime.now(last_dt.tzinfo)
    days_since = (now - last_dt).days

    if review_count == 0:
        state = "learning"
    elif review_count == 1:
        state = "stable"
    else:
        state = "mastered"

    # nextIntervalDays：learning=3 / stable=14 / mastered=45
    interval_map = {"learning": 3, "stable": 14, "mastered": 45}
    next_review_at = last_dt + timedelta(days=interval_map[state])
    overdue = now > next_review_at

    return {
        "state": state,
        "correctStreak": review_count,
        "reviewCount": review_count,
        "nextReviewAt": next_review_at.isoformat(),
        "lastReviewedAt": last_reviewed,
        "daysSinceLastReview": days_since,
        "overdue": overdue,
    }


# ============= API 输出组装 =============
def list_cards_with_state() -> list[dict]:
    """所有 KC 卡片 + 复习状态"""
    cards = scan_kc_cards()
    state = load_review_state()
    for c in cards:
        c["review"] = derive_card_state(c["id"], state)
    return cards


def get_stats() -> dict:
    """统计信息"""
    cards = list_cards_with_state()
    total = len(cards)
    by_state = {"learning": 0, "stable": 0, "mastered": 0}
    by_category = {}
    this_month = 0
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    for c in cards:
        st = c["review"]["state"]
        by_state[st] = by_state.get(st, 0) + 1
        cat = c["category"]
        by_category[cat] = by_category.get(cat, 0) + 1
        if c.get("created", "").startswith(current_month):
            this_month += 1
    # 知识周转率（mingxin 定义）
    activated_this_month = sum(
        1 for c in cards
        if c["review"].get("lastReviewedAt")
        and c["review"]["lastReviewedAt"].startswith(current_month)
    )
    turnover_rate = round(activated_this_month / total * 100, 1) if total else 0
    return {
        "total": total,
        "byState": by_state,
        "byCategory": by_category,
        "thisMonthNew": this_month,
        "thisMonthActivated": activated_this_month,
        "turnoverRate": turnover_rate,  # %
        "turnoverHealthy": turnover_rate >= 60,
    }


def get_today_review() -> list[dict]:
    """今日待复习的 KC（按 mingxin 状态机的"到期"逻辑）"""
    cards = list_cards_with_state()
    # overdue 或 nextIntervalDays 内到期
    today_cards = []
    for c in cards:
        rev = c["review"]
        if rev["state"] == "learning" and rev["reviewCount"] == 0:
            # 新卡 learning → 都在待复习里（按 mingxin "learning 3 天内首次复习"）
            today_cards.append(c)
        elif rev.get("overdue"):
            # 已复习过但到期的
            today_cards.append(c)
    return today_cards


def read_kc_card_full(kc_id: str) -> dict:
    """读单张 KC 卡片的完整正文（带复习状态）"""
    cards = scan_kc_cards()
    state = load_review_state()
    for c in cards:
        if c["id"] == kc_id:
            try:
                fpath = Path(c["path"])
                text = fpath.read_text(encoding="utf-8")
                meta, body = parse_frontmatter(text)
                # 关键修复：加上 review 状态（前端 openCard 依赖这个字段）
                result = {**c, "body": body, "frontmatter": meta}
                result["review"] = derive_card_state(kc_id, state)
                return result
            except Exception as e:
                return {**c, "body": f"读取失败: {e}", "frontmatter": {}, "review": derive_card_state(kc_id, state)}
    raise KeyError(f"找不到 KC 卡片: {kc_id}")


# ============= 单测 =============
if __name__ == "__main__":
    print("===扫描 KC 卡片===")
    cards = scan_kc_cards()
    print(f"共 {len(cards)} 张")
    for c in cards[:3]:
        print(f"  - [{c['category']}] {c['id']} · {c['title'][:30]}")
    print()
    print("===统计===")
    stats = get_stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print()
    print("===今日待复习（前 5）===")
    today = get_today_review()
    print(f"共 {len(today)} 张待复习")
    for c in today[:5]:
        print(f"  - [{c['category']}] {c['id']} · state={c['review']['state']} · overdue={c['review'].get('overdue')}")