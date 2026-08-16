# 工作台架构说明

> 这份文档讲清楚"工作台为什么这样分层"。读之前先看根目录的 `README.md` 了解"怎么用"。

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  浏览器（Chrome / Safari / Tailscale）                         │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  index.html  (单文件 SPA)                              │ │
│  │  - 全部 JS/CSS 内联（无打包步骤）                       │ │
│  │  - 8 个模块（见根目录 README.md）                       │ │
│  │  - 第三方依赖：marked.min.js + purify.min.js           │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────┬───────────────────────────────┘
                               │ fetch /api/* (知识库 + 云同步)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  WSL 后端  (python3 server.py · 监听 127.0.0.1:8765)           │
│  - /api/kc/cards         全部 KC 卡片列表                     │
│  - /api/kc/card?id=X     单张卡片全文                         │
│  - /api/kc/stats         复习统计                              │
│  - /api/review/today     今日待复习                            │
│  - /api/review/mark      标记已复习                            │
│  - /api/feeds/latest     行业新闻采集数据                      │
│  - /api/feeds/push       接收 cron 推送（分类 politics/finance/ai/subs）│
│  - /api/feeds/collect    前端点刷新 → 即时采集                 │
│  - /api/store            GET/POST 云同步数据仓库（store.json）  │
│  - /api/health           健康检查                              │
│                                                                 │
│  systemd 守护：/etc/systemd/system/dashboard-backend.service   │
│  - Slice=user.slice（WSL2 cgroup v2 必修，否则 Tailscale 不可达）│
│  - Restart=always（挂掉自动拉起）                              │
└──────────────────────────────┬───────────────────────────────┘
                               │ 文件读写
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  数据文件                                                       │
│  - api/data/feeds.json     采集的新闻流（atomic write）         │
│  - api/data/store.json     云同步数据（播客/打卡/股票池/选题池/今日计划）│
│  - D:\Obsidian Vault\📚 知识库\   KC 卡片正文（Obsidian vault）│
│  - 00_工具\review-state.json  KC 复习状态（与 mingxin-review 共用）│
└──────────────────────────────────────────────────────────────┘
                               ▲
                               │ 定时采集
┌──────────────────────────────────────────────────────────────┐
│  cron 任务（hermes cron）                                       │
│  - 每日 09:00  fetch_politics.py  →  时政                      │
│  - 每日 09:15  fetch_ai_news.py    →  AI 资讯                  │
│  - 每日 09:30  fetch_finance.py   →  财经                      │
│  - 推送方式：stdout JSON → dashboard_push.py → /api/feeds/push │
└──────────────────────────────────────────────────────────────┘
```

## 关键设计决策

### 1. 单文件 SPA（无打包）

- **优点**：修改 `index.html` 后**无需重启**就能看到效果；调试简单；移动到任何静态服务器直接打开就能用。
- **代价**：单文件 ~128KB 偏大（marked + purify 已分离）。模块化靠"分区标记"（`<!-- ==== 功能：xxx START ==== -->`）做软隔离。
- **不引框架**：用 React/Vue 反而要打包 + node_modules + watcher，**单文件纯 JS 才是真"零依赖"**。

### 2. 后端用 Python 标准库（无第三方依赖）

- `http.server.BaseHTTPRequestHandler + ThreadingMixIn` 直接跑
- 不引 Flask/FastAPI（部署简单但要多一步 `pip install`）
- 数据持久化用文件（`feeds.json`），不引 SQLite/Redis

### 3. systemd 守护（不是 cron watchdog）

- 早期 cron watchdog + setsid 在 WSL2 cgroup v2 下不可达（system.slice 网络隔离）
- 唯一解：`Slice=user.slice` + `Restart=always`
- 详见 `systemd/dashboard-backend.service`

### 4. 浏览器数据 vs 后端数据：分层 + 云同步

- **浏览器（localStorage）**：今日待办 / 股票池 / 选题池 / 打卡 / 播客 / 设置
  - 在工作台 UI 里**导入导出 JSON 备份**
  - **云同步（2026-08-05 B 方案）**：播客 / 打卡 / 股票池 / 选题池 / 今日计划 的 key
    在 `Store.set` 时**自动镜像到后端** `api/data/store.json`（`/api/store` 接口），
    启动时 `syncPull` 以后端为准覆盖本地 → 手机电脑通过 Tailscale 访问同一后端 = **天然一致、自动同步**
  - 设置项（主题 / 侧边栏状态）不同步，保持本机
- **后端（D 盘文件）**：KC 卡片正文 / 复习状态 / feeds.json 采集流 / store.json 云同步数据
  - 需手动备份（Obsidian vault 是 git 化的，review-state.json 需要单独 cp）

迁移到新机器 = `cp D:\IceFly\Dashboard\`（含 store.json）+ `bash deploy/install.sh`，10 分钟搞定。

## 模块功能矩阵

| 模块 | 数据来源 | 后端依赖 | 跨设备同步 |
|------|---------|---------|----------|
| 📅 今日计划 | localStorage + store.json | ✅ 8765 | ✅ 云同步（后端为准） |
| 📚 知识库 | D 盘 Obsidian vault | ✅ 8765 | ✅ 后端服务 |
| 📰 行业新闻 | cron + feeds.json | ✅ 8765 | ✅ 后端服务 |
| 🎧 精选播客 | localStorage + store.json | ✅ 8765 | ✅ 云同步（后端为准） |
| 📊 股票池 | localStorage + store.json | ✅ 8765 | ✅ 云同步（后端为准） |
| 🎯 选题池 | localStorage + store.json | ✅ 8765 | ✅ 云同步（后端为准） |
| ✅ 每日打卡 | localStorage + store.json | ✅ 8765 | ✅ 云同步（后端为准） |
| ⚙️ 设置 | localStorage | ❌ | ❌ 本机 |

## 安全边界

- **不进备份的**：API key（`Store.setSecret` 命名空间 `bysdash$secret:`）
- **不写公网的**：整个工作台纯本地，Tailscale 走加密隧道
- **不外发数据的**：浏览器 fetches 只到 `127.0.0.1:8765`（同机 loopback）
- **Cron 推送的**：POST 到 `127.0.0.1:8765/api/feeds/push`（同机 loopback）

## 性能边界

- 单后端 `ThreadingHTTPServer` 处理并发（之前单线程会因手机网络抖动卡死）
- 列表分页：KC 卡片 36 张全展示（不需要分页），feeds 限制 limit=10
- marked + purify 仅在打开 KC 弹窗时调用（不影响首页加载）

## 后续演进方向

| 方向 | 优先级 | 备注 |
|------|--------|------|
| PWA 离线缓存 | 低 | 现在完全在线/同机，不需 |
| 打包成 Electron | 低 | 桌面 app，但浏览器 PWA 已够用 |
| 接入实时通知 | 中 | 后端加 WebSocket 推 KC 复习提醒 |
| 多用户隔离 | 低 | 个人工作台不考虑 |