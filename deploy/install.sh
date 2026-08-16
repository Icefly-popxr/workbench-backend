#!/usr/bin/env bash
# ============================================================
# 然哥个人工作台 · 一键部署脚本（WSL2 / Linux 通用）
# 作用：把整个 Dashboard/ 目录部署到 / 部署到 systemd + cron
# 用法：bash deploy/install.sh [--skip-systemd] [--skip-cron] [--user-slice]
# ============================================================
set -e

# 默认值（可被参数覆盖）
SKIP_SYSTEMD=false
SKIP_CRON=false
WITH_USER_SLICE=true
DASHBOARD_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${USER:-star}"

echo "============================================="
echo "  然哥个人工作台 · 一键部署"
echo "  路径: $DASHBOARD_DIR"
echo "============================================="

for arg in "$@"; do
  case $arg in
    --skip-systemd) SKIP_SYSTEMD=true ;;
    --skip-cron)    SKIP_CRON=true ;;
    --no-slice)     WITH_USER_SLICE=false ;;
  esac
done

# ---------- 1. 安装依赖（Python 标准库已够，info-tracker 需要外网访问）----------
echo "▶ 检查依赖..."
python3 -c "import urllib.request, json" 2>/dev/null || {
  echo "✗ Python 3 标准库缺失，请先装 python3"
  exit 1
}
echo "  ✓ Python 3 OK"

# ---------- 2. 装 systemd unit（可选）----------
if [ "$SKIP_SYSTEMD" = false ]; then
  echo ""
  echo "▶ 部署 systemd 单元..."
  sudo cp "$DASHBOARD_DIR/systemd/dashboard-backend.service" \
          /etc/systemd/system/dashboard-backend.service
  sudo sed -i "s|User=star|User=$USER_NAME|g; s|Group=star|Group=$USER_NAME|g" \
          /etc/systemd/system/dashboard-backend.service

  # Slice 调整（WSL2 + systemd cgroup v2 必须 user.slice 否则手机端连不上）
  if [ "$WITH_USER_SLICE" = true ]; then
    sudo sed -i 's|^Slice=.*|Slice=user.slice|' /etc/systemd/system/dashboard-backend.service
  fi

  sudo systemctl daemon-reload
  sudo systemctl enable dashboard-backend
  sudo systemctl restart dashboard-backend
  sleep 2

  # 健康检查
  if curl -s --max-time 5 http://127.0.0.1:8765/api/health | grep -q '"ok": true'; then
    echo "  ✓ systemd 启动成功"
  else
    echo "  ✗ systemd 启动失败，看 journal："
    echo "    sudo journalctl -u dashboard-backend -n 30"
    exit 1
  fi
fi

# ---------- 3. 注册 cron（采集脚本）----------
if [ "$SKIP_CRON" = false ]; then
  echo ""
  echo "▶ 注册 cron 任务（行业新闻采集）..."

  # 3 个 cron 必须按绝对路径 + bash -lc（cron 子 shell PATH 可能被裁）
  CMD_TPL='python3 %s --limit 10 2>/dev/null | python3 %s %s'

  CMD_POLITICS=$(printf "$CMD_TPL" "$DASHBOARD_DIR/scripts/fetch_politics.py" "$DASHBOARD_DIR/scripts/dashboard_push.py" "politics")
  CMD_FINANCE=$(printf  "$CMD_TPL" "$DASHBOARD_DIR/scripts/fetch_finance.py"  "$DASHBOARD_DIR/scripts/dashboard_push.py" "finance")
  CMD_AI=$(printf       "$CMD_TPL" "$DASHBOARD_DIR/scripts/fetch_ai_news.py"   "$DASHBOARD_DIR/scripts/dashboard_push.py" "ai")

  # 2026-08-05 改造：自动检测调度方式（hermes cron 优先，crontab 兜底）
  #  - 检测到 hermes CLI → 用 hermes cron create（草帽团部署，能跟其他 agent 任务统一管理）
  #  - 没 hermes CLI → 用纯 Linux crontab（独立部署，不污染 ~/.hermes）
  if command -v hermes >/dev/null 2>&1; then
    echo "  检测到 hermes CLI → 用 hermes cron 调度"
    hermes cron create --name "行业新闻·时政采集（每日 09:00）" --schedule "0 9 * * *" \
      --script "$CMD_POLITICS" --no-agent --deliver local 2>&1 | tail -3
    hermes cron create --name "行业新闻·财经采集（每日 09:30）" --schedule "30 9 * * *" \
      --script "$CMD_FINANCE"  --no-agent --deliver local 2>&1 | tail -3
    hermes cron create --name "行业新闻·AI 资讯采集（每日 09:15）" --schedule "15 9 * * *" \
      --script "$CMD_AI"       --no-agent --deliver local 2>&1 | tail -3
  else
    echo "  没 hermes CLI → 用 Linux crontab 调度"
    CRON_FILE=$(mktemp)
    {
      echo "# 然哥工作台 · 行业新闻采集（2026-08-05 自动安装）"
      echo "0 9 * * *  $CMD_POLITICS"
      echo "30 9 * * * $CMD_FINANCE"
      echo "15 9 * * * $CMD_AI"
    } > "$CRON_FILE"
    crontab "$CRON_FILE" && rm "$CRON_FILE"
    echo "  ✓ crontab 已注册 3 个任务（每天 09:00 / 09:15 / 09:30）"
    echo "  查看：crontab -l | grep 行业新闻"
  fi
fi

# ---------- 4. 打印结果 ----------
echo ""
echo "============================================="
echo "  ✓ 部署完成"
echo "  工作台入口："
echo "    本机：http://127.0.0.1:8765/"
echo "    Tailscale：http://<你的 Tailscale IP>:8765/"
echo "============================================="
echo ""
echo "  后续可选："
echo "    手动跑一次采集：python3 $DASHBOARD_DIR/scripts/fetch_politics.py | python3 $DASHBOARD_DIR/scripts/dashboard_push.py politics"
echo "    看后端日志：sudo journalctl -u dashboard-backend -f"