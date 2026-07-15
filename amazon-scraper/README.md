# 🛒 Amazon Product Scraper & Price Monitor

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

亚马逊商品数据采集与价格监控系统 —— 从搜索列表页到详情页的全自动采集，SQLite 持久化存储，Web Dashboard 可视化，支持降价告警推送。

> 📝 **难度**: 中等，涵盖爬虫 / 数据库 / Web / 部署全链路

---

## ✨ 功能特性

| 模块 | 功能 |
|------|------|
| 🔍 **列表页采集** | 多关键词批量搜索，curl_cffi TLS 指纹模拟绕过反爬 |
| 📄 **详情页采集** | Playwright 异步并发 (3 窗口)，带重试 + 验证码检测 |
| 💾 **数据存储** | SQLite + SQLAlchemy ORM，支持 upsert 增量更新 |
| 📊 **Web Dashboard** | FastAPI + Bootstrap 5 + ECharts 价格走势图 |
| 📉 **价格监控** | 自动记录价格历史，检测降价并推送通知 |
| 🔔 **降价告警** | 支持 Telegram Bot / 控制台双通道通知 |
| ⏰ **定时调度** | APScheduler 定时采集 + 定期价格检查 |
| 🐳 **Docker 部署** | docker-compose 一键启动 Web + 调度器 |

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                     amazon-scraper                       │
├────────────┬────────────┬────────────┬─────────────────┤
│  crawler/  │  parser/   │  storage/  │     web/        │
│            │            │            │                 │
│ curl_cffi  │ Beautiful  │ SQLite     │ FastAPI         │
│ Playwright │ Soup+lxml  │ SQLAlchemy │ Jinja2+ECharts  │
│ (async)    │            │            │                 │
├────────────┴────────────┴────────────┴─────────────────┤
│  monitor/           CLI (click)       Docker            │
│  价格检测+通知      4 个子命令         docker-compose    │
└─────────────────────────────────────────────────────────┘
```

**数据流**：

```
列表页采集(curl_cffi) → 页面解析(BeautifulSoup) → SQLite(products)
                                                          │
详情页采集(Playwright async) ← 取出未采集的 ASIN ─────────┘
        │
        ▼
详情解析 → 更新 products + 记录 price_history
        │
        ▼
价格监控 → 降价检测 → Telegram/Console 通知
```

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.12+
- Playwright Chromium 浏览器

### 2. 安装依赖

```bash
# 克隆项目
git clone <your-repo-url>
cd amazon-scraper

# 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

### 3. 配置

编辑 `config.yaml`（可选，默认配置可直接使用）：

```yaml
keywords: ["手柄", "mouse", "keyboard"]  # 搜索关键词
max_list_pages: 5                         # 每个关键词采集页数
detail_concurrency: 3                     # 详情页并发数

# 可选：Telegram 通知
telegram_bot_token: "your-bot-token"
telegram_chat_id: "your-chat-id"
```

### 4. 运行

```bash
# 采集数据
# 采集所有配置的关键词（config.yaml 里的 mouse/keyboard）
python main.py crawl --all

# 指定单个关键词，采集 3 页
python main.py crawl -k "gaming mouse" -p 3

# 多个关键词
python main.py crawl -k "mouse,keyboard"

# 强制重新采集所有详情页（包括已采集过的）
python main.py crawl --all --force-details

# 控制并发数（默认 6，太大容易被封）
python main.py crawl --all --concurrency 3


# 查看 Web Dashboard
python main.py web
# 浏览器打开 http://localhost:8000

# 运行价格监控（一次性）
# 运行一次价格检查（记录当前价格快照）
python main.py monitor

# 设置降价阈值（降价超过 10% 才告警）
python main.py monitor --min-pct 10

# 检查并发送通知（需要先配置 Telegram）
python main.py monitor --notify


# 启动定时调度（每日采集 + 定期价格检查）
python main.py schedule
```

### 5. Docker 部署

```bash
docker-compose up -d
# Web Dashboard: http://localhost:8000
```

---

## 📁 项目结构

```
amazon-scraper/
├── app/
│   ├── crawler/               # 采集模块
│   │   ├── list_crawler.py    #   列表页 (curl_cffi)
│   │   ├── detail_crawler.py  #   详情页 (Playwright async)
│   │   └── cookie_manager.py  #   Cookie 自动管理
│   ├── parser/                # 解析模块
│   │   ├── list_parser.py     #   列表解析 (6层选择器兜底)
│   │   └── detail_parser.py   #   详情解析
│   ├── storage/               # 存储模块
│   │   ├── models.py          #   ORM 模型
│   │   ├── database.py        #   数据库引擎
│   │   └── repository.py      #   CRUD 仓库
│   ├── monitor/               # 监控模块
│   │   ├── price_checker.py   #   价格检测
│   │   └── notifier.py        #   通知推送
│   ├── web/                   # Web 模块
│   │   ├── app.py             #   FastAPI 应用
│   │   ├── routes.py          #   路由 + API
│   │   └── templates/         #   Jinja2 模板
│   ├── config.py             # 配置系统
│   └── logger.py             # 日志系统
├── tests/                     # 测试
├── data/                      # 数据文件
├── logs/                      # 日志文件
├── main.py                    # CLI 入口
├── config.yaml                # 配置文件
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 🛠️ 技术栈

| 层次 | 技术 | 选型理由 |
|------|------|---------|
| 列表页爬虫 | `curl_cffi` | 模拟 Chrome TLS 指纹，绕过 JA3/JA4 检测 |
| 详情页爬虫 | `playwright` (async) | 浏览器渲染 + 异步并发 3 窗口 |
| HTML 解析 | `BeautifulSoup4 + lxml` | 多重 CSS 选择器兜底，容错性强 |
| 数据库 | `SQLite + SQLAlchemy 2.0` | 零配置，面试 ORM 知识点多 |
| 配置管理 | `pydantic-settings + YAML` | 类型安全 + 文件热加载 |
| 日志 | `loguru` | 彩色输出 + 自动轮转 |
| CLI | `click` | 4 种子命令风格统一 |
| Web 框架 | `FastAPI + Jinja2` | 纯 Python 栈，高性能 |
| 图表 | `ECharts` (CDN) | 价格走势图，交互丰富 |
| 前端 | `Bootstrap 5` (CDN) | 响应式 Dashboard |
| 调度 | `APScheduler` | 轻量定时，无需 Redis |
| 部署 | `Docker + docker-compose` | 一键部署，双服务协同 |

---

## 🔧 反爬策略

本项目针对 Amazon 的 5 层反爬体系设计了对应方案：

| Amazon 反爬层 | 本项目对策 |
|---------------|-----------|
| 1. TLS 指纹 (JA3/JA4) | `curl_cffi impersonate="chrome120"` 模拟浏览器指纹 |
| 2. HTTP/2 SETTINGS 帧 | curl_cffi 自动处理 |
| 3. WAF Token 验证 | `cookie_manager.py` 自动获取有效 Cookie |
| 4. 行为分析 | 随机延迟 (3-6s) + Referer 链完整 |
| 5. 静默 CAPTCHA | Playwright 浏览器渲染 + 验证码页面检测 |

---

## 📊 面试话术参考

> "我独立完成了一个全栈项目——亚马逊商品采集与价格监控系统。**爬虫层**用 curl_cffi 的 TLS 指纹伪装和 Playwright 浏览器渲染双引擎，绕过了 Amazon 的多层反爬。**架构上**采用了流水线模式，支持断点续爬和异步并发，详情页采集速度从串行12分钟优化到并发3分钟。**数据层**用 SQLAlchemy ORM + SQLite，实现了 upsert 增量更新和 price_history 价格快照。**业务上**实现了降价自动检测和 Telegram 通知推送，配有 FastAPI + ECharts 的 Web Dashboard。整个项目通过 Docker Compose 一键部署。"

---

## 📝 License

MIT License — 自由使用，学习交流目的。

---

## 🤝 贡献

欢迎 Star ⭐ 和 PR！如果觉得有帮助，请分享给需要的同学。

---

> 💡 **提示**: Amazon 的反爬机制持续升级。如果遇到采集失败，请优先检查 Cookie 是否过期，或适当增加 `request_delay` 参数。
