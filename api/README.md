# API 后端说明

> 监听 `127.0.0.1:8765`，纯 Python 标准库，无第三方依赖。

## 文件说明

| 文件 | 作用 |
|------|------|
| `server.py` | 主入口（HTTP handler + 路由） |
| `scan_kc.py` | 扫描 D 盘 Obsidian vault 的 KC 卡片 |
| `feeds_store.py` | feeds.json 的读写（atomic write） |
| `sync_store.py` | 云同步数据仓库：store.json 的读写（原子写） |
| `data/feeds.json` | 行业新闻采集流（自动写入） |
| `data/store.json` | 云同步数据（播客/打卡/股票池/选题池/今日计划，手机电脑一致） |

## API 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/health` | GET | 健康检查（`{"ok": true}`） |
| `/api/kc/cards` | GET | 全部 KC 卡片列表（带复习状态） |
| `/api/kc/card?id=X` | GET | 单张卡片全文 |
| `/api/kc/stats` | GET | 复习统计（总数 / 分类 / 月度新增） |
| `/api/review/today` | GET | 今日待复习列表 |
| `/api/review/mark` | POST | 标记已复习（`{id, note}`） |
| `/api/feeds/latest?category=X&limit=N` | GET | 行业新闻数据 |
| `/api/feeds/push` | POST | cron 推送用（`{category, items}`） |
| `/api/feeds/collect` | POST | 前端点「刷新」→ 即时跑一次采集脚本（`{category}`） |
| `/api/store` | GET | 云同步数据全量拉取（返回 `{data: {...}}`） |
| `/api/store` | POST | 云同步写入：`{key, value}` 单 key，或 `{data: {...}}` 批量（首次迁移） |

## 跨域

所有响应带 `Access-Control-Allow-Origin: *`，工作台 PWA 可以直接 fetch。

## 单线程死锁问题

> 历史教训：早期 `HTTPServer` 是单线程，手机网络抖动导致 socket 卡死 → 整页无响应。

修复：见 `class ThreadingHTTPServer(ThreadingMixIn, HTTPServer)`，**每个请求独立线程**。

## systemd 守护

unit 文件在 `../systemd/dashboard-backend.service`，关键配置：

- `Slice=user.slice`（WSL2 cgroup v2 必修，**否则 Tailscale 不可达**）
- `Restart=always`（挂掉自动拉起）
- `WorkingDirectory=/mnt/d/IceFly/Dashboard/api`

## 手动跑（不开 systemd）

```bash
cd /mnt/d/IceFly/Dashboard/api
python3 server.py
```

## 数据流向

```
cron 采集脚本             浏览器
  ↓ ↓ ↓                  ↑ ↑
fetch_politics.py    ───→  /api/feeds/push
fetch_finance.py     ───→     ↓
fetch_ai_news.py     ───→  feeds.json (atomic)
                          ↓
                       浏览器拉 /api/feeds/latest?category=...
                          ↓
                       News 模块渲染
```