#!/usr/bin/env python3
"""
AI 资讯采集脚本（2026-08-05 落地 · 工作台行业新闻模块专用）
源头：① AIHOT 中文 AI 热点（search_aihot.py）
     ② 稀土掘金 技术（search_juejin.py）
     ③ 量子位 AI（search_qbitai.py）
注：复用 info-tracker skill 已有的 3 个采集脚本，不重复造轮子
输出：stdout JSON list → 走 dashboard_push.py 推送到 feeds.json（category=ai）

使用：
  python3 fetch_ai_news.py [--limit 10] | python3 dashboard_push.py ai
  python3 fetch_ai_news.py --dry-run
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# info-tracker skill 的 3 个中文 AI 源脚本
# 路径策略（2026-08-05 重构 · 独立项目原则）：
#   - 优先用脚本相对路径：../scripts/（工作台自带的副本，零外部依赖）
#   - 兼容老路径 ~/.hermes/skills/info-tracker/scripts/（草帽团老部署，运行时无副本则用）
#   - 都找不到则跳过对应源（不让脚本崩）
_INFO_TRACKER_DIR = (
    Path(__file__).parent  # 工作台 scripts/ 自带副本（开箱即用）
    if (Path(__file__).parent / "search_aihot.py").exists()
    else Path.home() / ".hermes" / "skills" / "info-tracker" / "scripts"   # 老路径兼容
)

SOURCES = {
    "aihot":  _INFO_TRACKER_DIR / "search_aihot.py",
    "juejin": _INFO_TRACKER_DIR / "search_juejin.py",
    "qbitai": _INFO_TRACKER_DIR / "search_qbitai.py",
}

# 中文友好关键词（确保只收中文标题；过滤 arxiv/github 风格的英文）
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def run_source(name, limit):
    """调子脚本，stdout 是 markdown 格式的简报；解析回 {title, url, source, summary}"""
    script = SOURCES.get(name)
    if not script or not script.exists():
        print(f"[ERROR] 子脚本不存在: {script}", file=sys.stderr)
        return []

    # aihot / qbitai / juejin 的输出格式:
    #   **标题** — 来源
    #   摘要多行
    #   https://...
    # 简化为：调子脚本 → 解析 markdown → 提取 title/url
    try:
        if name == "aihot":
            r = subprocess.run(
                ["python3", str(script), "AI", str(limit)],
                capture_output=True, text=True, timeout=30,
            )
        elif name in ("juejin", "qbitai"):
            # 2026-08-05 修复：juejin/qbitai 用 --limit N（位置参数错位 → 报错 unrecognized）
            r = subprocess.run(
                ["python3", str(script), "--limit", str(limit)],
                capture_output=True, text=True, timeout=30,
            )
    except Exception as e:
        print(f"[ERROR] {name} 子进程失败: {e}", file=sys.stderr)
        return []

    if r.returncode != 0:
        print(f"[ERROR] {name} 子脚本非零退出: {r.stderr[:200]}", file=sys.stderr)
        return []

    return parse_markdown_report(r.stdout, name, limit)


def parse_markdown_report(md, source, limit):
    """解析 aihot/juejin/qbitai 输出的 markdown 简报
    常见格式：
      1. **标题** — 来源
         摘要...
         https://url
    """
    items = []
    # 拆行，按数字编号 `数字.` 起头
    lines = md.split("\n")
    current = None
    summary_buf = []
    for line in lines:
        # 匹配 "数字. **标题**"
        m = re.match(r"\s*(\d+)\.\s+\*\*(.+?)\*\*", line)
        if m:
            # 提交前一条
            if current:
                current["summary"] = " ".join(summary_buf).strip()[:200]
                items.append(current)
            current = {
                "title": m.group(2).strip(),
                "source": SOURCE_LABEL.get(source, source),
            }
            summary_buf = []
            continue
        # URL 行
        url_m = re.match(r"\s*(https?://\S+)\s*$", line)
        if url_m and current:
            current["url"] = url_m.group(1).strip()
            continue
        # 其他行：归到 summary
        if current and line.strip() and not line.startswith("**"):
            summary_buf.append(line.strip())
    # 收尾
    if current:
        current["summary"] = " ".join(summary_buf).strip()[:200]
        items.append(current)

    # 过滤：只要中文标题
    items = [it for it in items if CHINESE_PATTERN.search(it.get("title", ""))]
    # 过滤：必须有 URL
    items = [it for it in items if it.get("url")]
    # 截断 limit
    return items[:limit]


SOURCE_LABEL = {
    "aihot": "AIHOT",
    "juejin": "稀土掘金",
    "qbitai": "量子位",
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", "-n", type=int, default=10)
    p.add_argument("--dry-run", action="store_true", help="只打印不推送")
    p.add_argument("--source", default="all", choices=["all", "aihot", "juejin", "qbitai"])
    args = p.parse_args()

    items = []
    # 2026-08-05 修复：每个源限额 limit/n，避免 aihot 一个源就填满整个 list
    # 实际"每个源"内部还会再 limit 一次 + 主函数再 limit 一次，3 层保护
    per_source_limit = max(3, (args.limit + 2) // 3)  # 向上取整，至少 3 条
    # 优先 aihot（最新最热）
    if args.source in ("all", "aihot"):
        items.extend(run_source("aihot", per_source_limit))
    if args.source in ("all", "qbitai"):
        items.extend(run_source("qbitai", per_source_limit))
    if args.source in ("all", "juejin"):
        items.extend(run_source("juejin", per_source_limit))

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