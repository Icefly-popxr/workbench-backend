#!/bin/bash
# fetch_news_daily.sh — 行业新闻 3 通道采集包装脚本（供 cron 调用）
# 用法: bash fetch_news_daily.sh <politics|finance|ai>
# 每个通道: fetch_xxx.py --limit 10 → dashboard_push.py xxx
# 2026-08-06 创建：原 cron 把整条管道塞进 script 字段导致 Script not found，
# 拆成 .sh 后 script 字段指向本文件。

CHANNEL="$1"
BASE="/mnt/d/IceFly/Dashboard/scripts"

case "$CHANNEL" in
  politics)
    python3 "$BASE/fetch_politics.py" --limit 10 2>/dev/null | python3 "$BASE/dashboard_push.py" politics
    ;;
  finance)
    python3 "$BASE/fetch_finance.py" --limit 10 2>/dev/null | python3 "$BASE/dashboard_push.py" finance
    ;;
  ai)
    python3 "$BASE/fetch_ai_news.py" --limit 10 2>/dev/null | python3 "$BASE/dashboard_push.py" ai
    ;;
  *)
    echo "❌ 用法: fetch_news_daily.sh <politics|finance|ai>" >&2
    exit 2
    ;;
esac
exit $?
