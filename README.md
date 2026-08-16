# 然哥个人工作台

> **手机端 PWA 个人工作台** —— 8 个功能模块（今日计划 / 知识库 / 行业新闻 / 精选播客 / 股票池 / 选题池 / 每日打卡 / 设置），单文件 SPA + Python 标准库后端，离线可用，Tailscale 内网穿透，手机电脑数据云端同步。

![项目演示](docs/screenshot.png)

## ✨ 特点

- **🪶 零打包**：单文件 `index.html`，所有 CSS/JS 内联，**改完即可见**
- **📦 零依赖前端**：纯原生 JS + marked.js（KC 卡片 markdown 渲染）+ DOMPurify（XSS 防护）
- **🐍 零依赖后端**：Python 3 标准库（`http.server` + `ThreadingMixIn`），**不需要 `pip install`**
- **📱 PWA 友好**：加桌面图标 → 全屏启动；Tailscale 异地访问
- **🔒 数据本地**：核心数据存 D 盘 Obsidian vault + 浏览器 localStorage，**零云依赖**
- **☁️ 多端同步**：播客 / 打卡 / 股票池 / 选题池 / 今日计划自动镜像到后端 store.json，手机电脑**天然一致**
- **⏰ 定时采集**：cron 自动拉时政 / 财经 / AI 资讯 3 个分类，每天更新
- **🧰 一键部署**：自带 `deploy/install.sh`，新机器 10 分钟搭完

## 🚀 30 秒上手

### 选项 A：纯前端（不需要后端，6 个模块可用）

```bash
# 1. 打开浏览器访问
http://127.0.0.1:8765/         ← 如果后端已起
file:///D:/IceFly/Dashboard/index.html   ← 直接双击也行
```

### 选项 B：完整部署（8 个模块全部可用）

```bash
# 1. 把整个目录复制到目标机器
#    Windows:  D:\IceFly\Dashboard\
#    WSL:      /mnt/d/IceFly/Dashboard/  (或软链)
# 2. 一键安装
cd /mnt/d/IceFly/Dashboard
bash deploy/install.sh
# 3. 打开
#    本机：http://127.0.0.1:8765/
#    异地（Tailscale）：http://<你的 Tailscale IP>:8765/
```

**install.sh 干了什么**：

1. 装 systemd 守护单元（`/etc/systemd/system/dashboard-backend.service`）
2. **关键**：自动设置 `Slice=user.slice`（WSL2 cgroup v2 必需，否则 Tailscale 外部不可达）
3. 注册 3 个 cron 任务（时政 / 财经 / AI 资讯 每日 9 点采）

参数：
- `--skip-systemd`：跳过 systemd，只跑前端
- `--skip-cron`：跳过 cron 任务注册
- `--no-slice`：不强制 user.slice（非 WSL2 场景）

## 📁 目录结构

```
Dashboard/
├── README.md                          ← 本文件
├── index.html                         ← 单文件 SPA（128KB，UI + JS 全在这）
├── manifest.json                      ← PWA 配置
├── icon.png + avatar-source.png        ← 图标
├── marked.min.js + purify.min.js      ← KC 弹窗依赖
├── 风格预览.html                      ← 早期风格选择工具
│
├── api/                               ← Python 后端（标准库）
│   ├── server.py                      ← 入口（监听 8765）
│   ├── scan_kc.py                     ← 扫描 D 盘 Obsidian KC 卡片
│   ├── feeds_store.py                 ← 行业新闻数据存储
│   ├── sync_store.py                  ← 多端同步数据仓库（store.json 读写）
│   ├── data/feeds.json                ← 采集流（atomic write）
│   ├── data/store.json                ← 云同步数据（手机电脑一致）
│   └── README.md                      ← 后端详细文档
│
├── scripts/                           ← cron 拉的采集脚本（开源准备）
│   ├── dashboard_push.py              ← 通用 push 到 /api/feeds/push
│   ├── fetch_politics.py              ← 时政采集（人民网 + 中新网 + 知乎热榜）
│   ├── fetch_finance.py               ← 财经采集（36kr 财经关键词）
│   └── fetch_ai_news.py               ← AI 资讯（aihot + 掘金 + 量子位）
│
├── systemd/
│   └── dashboard-backend.service      ← systemd 单元（含 Slice=user.slice）
│
├── deploy/
│   └── install.sh                     ← 一键部署（systemd + cron + 路径调整）
│
└── docs/
    └── ARCHITECTURE.md                ← 架构细节（为什么这样设计）
```

## 🧩 功能模块

| 模块 | 路径 | 数据 | 后端 | 跨设备同步 |
|------|------|------|------|----------|
| 📅 今日计划 | `index.html#page-today` | localStorage + store.json | ✅ | ✅ 自动 |
| 📚 知识库 | `index.html#page-knowledge` | D 盘 Obsidian vault | ✅ | ✅ 后端服务 |
| 📰 行业新闻 | `index.html#page-hot` | cron + feeds.json | ✅ | ✅ 后端服务 |
| 🎧 精选播客 | `index.html#page-podcast` | localStorage + store.json | ✅ | ✅ 自动 |
| 📊 股票池 | `index.html#page-stock` | localStorage + store.json | ✅ | ✅ 自动 |
| 🎯 选题池 | `index.html#page-topic` | localStorage + store.json | ✅ | ✅ 自动 |
| ✅ 每日打卡 | `index.html#page-checkin` | localStorage + store.json | ✅ | ✅ 自动 |
| ⚙️ 设置 | `index.html#page-settings` | localStorage | ❌ | ❌ 本机 |

## 💾 数据备份

工作台数据**分层存放**：

| 数据类型 | 位置 | 备份方式 |
|---------|------|---------|
| 今日待办 / 股票池 / 选题池 / 打卡 / 播客 | localStorage + `api/data/store.json` | 自动镜像到后端（手机电脑一致）· 含在 Dashboard/ 目录里 |
| API key / 敏感数据 | localStorage `bysdash$secret:` | **故意不进备份**（防泄漏） |
| KC 复习状态 | `D:\Obsidian Vault\🤖 草帽团\00_工具\review-state.json` | 手动备份（git 化） |
| 行业新闻采集 | `api/data/feeds.json` | 包含在 Dashboard/ 目录里 |
| KC 卡片正文 | D 盘 Obsidian vault | Git 化（自动备份） |

**完整迁移流程**：
1. 复制整个 `D:\IceFly\Dashboard\` 目录到新机器（含 store.json / feeds.json，云同步数据直接带走）
2. 复制 D 盘 Obsidian vault（git clone）
3. 跑 `bash deploy/install.sh`
4. （手机端）在浏览器里"恢复备份"导入之前的 localStorage

## ⚙️ 系统要求

- **WSL2**（Windows 11 推荐，开 systemd）或任意 Linux
- **Python 3.7+**（WSL 默认有）
- **systemd**（WSL2 需 `/etc/wsl.conf` 加 `[boot] systemd=true`）
- **可选 Tailscale**（异地访问手机端需要）

## 🛠️ 开发

### 改前端

```bash
# 1. 编辑 index.html
# 2. 浏览器 Ctrl+Shift+R 硬刷新
# 3. 没有构建步骤，所见即所得
```

### 改后端

```bash
# 1. 编辑 api/*.py
# 2. 重启服务
sudo systemctl restart dashboard-backend
# 3. 看日志
sudo journalctl -u dashboard-backend -f
```

### 改采集脚本

```bash
# 1. 编辑 scripts/fetch_*.py
# 2. 手动跑一次测试
python3 scripts/fetch_politics.py --dry-run --limit 5
# 3. 真推
python3 scripts/fetch_politics.py --limit 10 | python3 scripts/dashboard_push.py politics
# 4. 看 feeds.json
cat api/data/feeds.json | python3 -m json.tool | head -30
```

### 关键设计约束

- **不引打包工具**（npm/webpack/vite）：单文件直接可读，便于迁移
- **不引前端框架**（React/Vue）：纯原生 JS + 模块化注释分区
- **不引后端框架**（Flask/FastAPI）：Python 标准库，部署零依赖
- **不引数据库**：文件即数据库（feeds.json atomic write）

详细架构说明：`docs/ARCHITECTURE.md`

## 🐛 故障排查

| 现象 | 原因 | 修复 |
|------|------|------|
| 手机端 `curl HTTP 000` | WSL2 cgroup 隔离（system.slice 不可达） | `Slice=user.slice`（见 `systemd/dashboard-backend.service`） |
| 整页空白无 JS | inline `<script>` 语法错（`/` 误写 `'`） | 提取后 `node --check`（见 `scripts` 跑法） |
| KC 卡片只显示 raw markdown | 没装 marked.js / DOMPurify | 已在 `index.html` 头部引，确认 2 个 .js 文件存在 |
| 后端单线程阻塞（手机网络抖动触发） | 没 `ThreadingMixIn` | 已在 `api/server.py` 启用 |
| feeds 一直空 | cron 没起 + 后端没装 | 看 `deploy/install.sh` 是否完整跑过 |

## 📜 许可

MIT（待定 — 看你最终想怎么定）

## 🙏 致谢

- 底层架构 fork 自 [bys-personal-dashboard](https://...)（fork 时刻 2026-08-05）
- 行业新闻 AI 源：`aihot.virxact.com` / 稀土掘金 / 量子位
- 时政源：人民网时政 RSS / 中新网时政 RSS / 知乎热榜 API
- 财经源：36kr 创投 RSS
- 知识库结构：Obsidian PARA + Wikis

---

**最后更新：2026-08-05 · 开源准备版**
