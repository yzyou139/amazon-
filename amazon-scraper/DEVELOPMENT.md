# Amazon Scraper — 项目开发文档

> **版本**: 2.0.0  
> **最后更新**: 2026-07-15  
> **技术栈**: Python 3.12+ / curl_cffi / Playwright / FastAPI / SQLAlchemy

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [模块详解](#3-模块详解)
   - [3.1 配置系统 (config.py)](#31-配置系统-configpy)
   - [3.2 日志系统 (logger.py)](#32-日志系统-loggerpy)
   - [3.3 Cookie 管理器 (cookie_manager.py)](#33-cookie-管理器-cookie_managerpy)
   - [3.4 列表页采集 (list_crawler.py)](#34-列表页采集-list_crawlerpy)
   - [3.5 详情页采集 (detail_crawler.py)](#35-详情页采集-detail_crawlerpy)
   - [3.6 列表页解析 (list_parser.py)](#36-列表页解析-list_parserpy)
   - [3.7 详情页解析 (detail_parser.py)](#37-详情页解析-detail_parserpy)
   - [3.8 数据库模型 (models.py)](#38-数据库模型-modelspy)
   - [3.9 数据仓库 (repository.py)](#39-数据仓库-repositorypy)
   - [3.10 价格监控 (price_checker.py + notifier.py)](#310-价格监控-price_checkerpy--notifierpy)
   - [3.11 Web 服务 (routes.py + templates/)](#311-web-服务-routespy--templates)
   - [3.12 CLI 入口 (main.py)](#312-cli-入口-mainpy)
4. [核心设计模式](#4-核心设计模式)
5. [反爬策略技术详解](#5-反爬策略技术详解)
6. [数据库设计](#6-数据库设计)
7. [如何移植到其他网站](#7-如何移植到其他网站)
8. [常见问题排查](#8-常见问题排查)

---

## 1. 项目概述

这是一个 **商品数据采集 + 价格监控** 的全栈项目，适用于电商网站（以 Amazon 为例）的数据抓取。项目实现了从搜索列表页到商品详情页的全自动采集，SQLite 持久化存储，Web Dashboard 可视化展示，以及降价自动告警。

### 适用场景

- 学习爬虫技术、反爬对抗
- 简历项目（全栈：爬虫 → 数据库 → Web → 部署）
- 电商选品数据分析

### 核心难点

| 难点 | 解决方案 |
|------|---------|
| Amazon WAF 拦截 | curl_cffi TLS 指纹模拟 |
| 前端反爬 | Playwright 浏览器渲染 |
| 异步采集效率 | asyncio + Semaphore 并发控制 |
| 数据一致性 | SQLAlchemy ORM + upsert |
| 页面结构多变 | 4-7 层 CSS 选择器兜底 |

---

## 2. 系统架构

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────┐
│  CLI (main.py)                                           │
│  ┌────────┐ ┌──────────┐ ┌────────┐ ┌────────┐         │
│  │ crawl  │ │ monitor  │ │  web   │ │schedule│         │
│  └───┬────┘ └────┬─────┘ └───┬────┘ └───┬────┘         │
│      │           │           │          │               │
│      ▼           ▼           ▼          ▼               │
│  ┌─────────────────────────────────────────────┐        │
│  │              app/ 核心模块                   │        │
│  │                                              │        │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │        │
│  │  │ crawler/ │→│ parser/  │→│ storage/ │  │        │
│  │  │ 采集层   │  │ 解析层   │  │ 持久化   │  │        │
│  │  └──────────┘  └──────────┘  └──────────┘  │        │
│  │        │              │                    │        │
│  │  ┌─────┴──────────────┴─────────────┐      │        │
│  │  │       monitor/   web/            │      │        │
│  │  │       价格监控   可视化           │      │        │
│  │  └──────────────────────────────────┘      │        │
│  └─────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
┌────────────────────────────────────────────────────────────┐
│                  数据采集流水线                              │
│                                                            │
│  查询关键词列表 (config.yaml)                                │
│        │                                                   │
│        ▼                                                   │
│  ┌─────────────────────┐                                   │
│  │ 列表页采集 (curl_cffi)│ ←── Cookie 管理器自动获取          │
│  │ 多页、多关键词        │ ←── TLS 指纹模拟                   │
│  └─────────┬───────────┘                                   │
│            │ 原始 HTML (含 &&& 分隔的 dispatch)              │
│            ▼                                               │
│  ┌─────────────────────┐                                   │
│  │ 列表页解析 (BS4)     │ ←── 6-7 层 CSS 选择器兜底           │
│  │ 提取 ASIN/价格/评分等 │ ←── 按 ASIN 去重                  │
│  └─────────┬───────────┘                                   │
│            │ 结构化商品数据           ┌────────────┐        │
│            ├─────────────────────────│ Products 表 │        │
│            ▼                         └────────────┘        │
│  ┌─────────────────────┐                                   │
│  │ 详情页采集 (Playwright)│ ←── 异步并发 + Semaphore         │
│  │ ASIN → /dp/{ASIN}   │ ←── 重试 + WAF 检测               │
│  └─────────┬───────────┘                                   │
│            │ 详情页 HTML                                     │
│            ▼                                               │
│  ┌─────────────────────┐          ┌────────────┐           │
│  │ 详情页解析 (BS4)     │─────────│ Products 表 │           │
│  │ 标题/品牌/规格/图片等 │          │ (字段补充)  │           │
│  └─────────────────────┘          └────────────┘           │
│                                                            │
│  ┌─────────────────────┐          ┌──────────────┐         │
│  │ 价格监控 (monitor)  │─────────│ PriceHistory │         │
│  │ 记录快照 → 检测降价   │          │ 表          │         │
│  │ → 推送通知          │          └──────────────┘         │
│  └─────────────────────┘                                   │
│                                                            │
│  ┌─────────────────────┐                                   │
│  │ Web Dashboard       │ ←── FastAPI + ECharts            │
│  │ http://localhost:8000│                                   │
│  └─────────────────────┘                                   │
└────────────────────────────────────────────────────────────┘
```

### 2.3 为什么列表页和详情页用不同的采集技术？

| 对比项 | 列表页 (curl_cffi) | 详情页 (Playwright) |
|--------|-------------------|-------------------|
| WAF 拦截率 | 较低（POST + Cookie 可绕） | 高（需浏览器渲染） |
| 数据量 | 10-50 页 | 100-500 个页面 |
| 速度要求 | 高（批量快速请求） | 低（单页 3-6s） |
| 浏览器开销 | 不可接受 | 可接受（并发控制） |
| **核心原因** | curl_cffi 能模拟 TLS 指纹，比 requests 更接近真实浏览器 | 详情页反爬更严格，需要完整浏览器环境 |

---

## 3. 模块详解

### 3.1 配置系统 (`app/config.py`)

**技术**: pydantic-settings + PyYAML

**设计思路**:
- 所有可配置的项集中在 `config.yaml`，读者无需改代码
- `pydantic-settings` 提供类型安全和 IDE 自动补全
- 支持 YAML 文件 + 环境变量双重覆盖（环境变量优先级更高，前缀 `AMAZON_`）

**核心代码**:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AMAZON_")

    keywords: list[str] = ["mouse", "keyboard"]   # 搜索关键词
    max_list_pages: int = 5                        # 每关键词采集页数
    detail_concurrency: int = 6                    # 详情页并发数
    request_delay_min: float = 2.0                 # 请求最小间隔（秒）
    request_delay_max: float = 4.0                 # 请求最大间隔（秒）
    database_url: str = "sqlite:///data/amazon.db"

    @classmethod
    def from_yaml(cls) -> "Settings":
        config_data = _yaml_config_source(cls)
        return cls(**config_data)

settings = Settings.from_yaml()  # 全局单例
```

**关键点**:
- `env_prefix="AMAZON_"` 使环境变量 `AMAZON_DATABASE_URL` 能覆盖 YAML 配置
- `from_yaml()` 先加载 YAML 再传入 `Settings()`，实现文件 + 环境变量叠加

---

### 3.2 日志系统 (`app/logger.py`)

**技术**: loguru

**设计思路**:
- 替代 Python 标准库 `logging`，loguru 开箱即用
- 控制台彩色输出 + 文件日志双通道
- 自动轮转（每天切分，保留 7 天）

**核心配置**:

```python
logger.remove()  # 移除默认 handler

# 控制台 — 彩色
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
           level="INFO", colorize=True)

# 全量文件 — 轮转
logger.add("logs/app_{time:YYYY-MM-DD}.log", level="DEBUG", rotation="00:00", retention="7 days")

# 错误专用
logger.add("logs/error_{time:YYYY-MM-DD}.log", level="ERROR", rotation="00:00", retention="30 days")
```

**为什么不用 print？**
- 日志分级（DEBUG/INFO/WARNING/ERROR）
- 自动写入文件，方便排查问题
- 轮转避免日志文件无限膨胀

---

### 3.3 Cookie 管理器 (`cookie_manager.py`)

**技术**: Playwright + 文件缓存

**设计思路**: Cookie 获取有三个优先级

```
手动 Cookie 文件 (cookies_manual.json)  →  最高优先级，用户从浏览器复制
    ↓ (不存在或无效)
内存缓存 (1 小时内)                       →  避免频繁获取
    ↓ (过期)
文件缓存 (cookies.json)                  →  跨会话复用
    ↓ (过期或无效)
Playwright 自动获取                      →  打开浏览器获取最新 Cookie
    ↓ (失败)
抛出异常 + 提示手动设置
```

**核心代码**:

```python
def get_cookies(self, force_refresh=False) -> dict:
    # 0. 手动 Cookie 文件
    manual = self._load_manual()
    if manual and self.is_valid(manual):
        return manual

    if not force_refresh:
        # 1. 内存缓存
        if self._cookies and (time.time() - self._fetched_at) < self.CACHE_TTL:
            return self._cookies
        # 2. 文件缓存
        if self._load_from_file():
            return self._cookies

    # 3. 自动获取
    cookies = self._fetch_fresh_cookies()
    ...
    return cookies
```

**Playwright 反检测配置**:

```python
browser = p.chromium.launch(headless=True, args=[
    "--disable-blink-features=AutomationControlled",  # 隐藏自动化标志
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-web-security",
])
page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });  # 移除 webdriver
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });  # 假装有插件
""")
```

**手动 Cookie 文件格式** (`cookies_manual.json`):

```json
{
  "aws-waf-token": "xxx",
  "session-id": "xxx",
  "session-token": "xxx",
  "ubid-main": "xxx"
}
```

获取方法：浏览器打开 amazon.com → F12 → Application → Cookies → 全选复制。

---

### 3.4 列表页采集 (`list_crawler.py`)

**技术**: curl_cffi（替代 requests）

**设计思路**:
- 为什么不用 `requests`？Amazon 检测 Python 的 TLS 指纹（JA3），`requests` 的指纹和浏览器差太多，直接返回 503。
- `curl_cffi` 使用 curl 的底层实现，能模拟 Chrome/Firefox/Safari 的完整 TLS 指纹。

**核心函数**:

```python
def crawl_list_page(keyword: str, page_num: int, cookies: dict) -> Optional[str]:
    params = {"k": keyword, "page": str(page_num), ...}
    response = cffi_requests.post(
        "https://www.amazon.com/s/query",
        params=params,
        cookies=cookies,
        headers=headers,           # 46 个请求头，模拟真实浏览器
        json={"customer-action": "pagination"},
        impersonate="chrome120",   # ← 核心: 模拟 Chrome TLS 指纹
        timeout=30,
    )
```

**关键参数**:

| 参数 | 作用 |
|------|------|
| `impersonate="chrome120"` | 模拟 Chrome 120 的 TLS 指纹和 HTTP/2 帧 |
| `headers` (46 个字段) | 包含 sec-ch-ua、viewport-width 等浏览器特征头 |
| `cookies` | Cookie 管理器自动获取，含 aws-waf-token |

**Amazon 列表页返回结构**:

Amazon 的搜索页面返回的不是干净 HTML，而是用 `&&&` 分隔的 dispatch 数组：

```
[null,"data-slot-1",{"html":"<div>...</div>","asin":"B0XXX"}] &&&
[null,"data-slot-2",{"html":"<div>...</div>","asin":"B0YYY"}] &&&
```

每个 dispatch 数组的第三个元素包含 HTML 片段和该片段的"主 ASIN"。列表页采集的原始数据就是这种带分隔符的文本，由解析器处理。

---

### 3.5 详情页采集 (`detail_crawler.py`)

**技术**: Playwright async API + asyncio.Semaphore

**设计思路**:
- 详情页反爬更严，必须用完整浏览器渲染
- 用 `asyncio.Semaphore(6)` 控制并发数（一次最多 6 个页面同时加载）
- 不拦截任何响应（包括 5539 字节的 WAF 页），交给解析器决定能提取到什么

**核心函数**:

```python
async def _crawl_single_detail(asin, browser, semaphore):
    async with semaphore:  # 控制并发数
        page = await browser.new_page()
        await page.goto(f"https://www.amazon.com/dp/{asin}",
                        wait_until="domcontentloaded")

        # 等待商品标题（有最好，没有也不强求）
        try:
            await page.wait_for_selector("#productTitle", timeout=10000)
        except Exception:
            pass

        await page.wait_for_timeout(500)  # JS 渲染时间
        html_text = await page.content()
        return (asin, html_text, None)
```

**为什么不拦截 WAF 页？**

WAF 拦截（5539 字节）虽然拿不到完整商品信息，但页面中可能包含部分结构化数据（如 JSON-LD、meta 标签）。解析器会尝试从这些数据中提取信息，能提取到什么就存什么。

**浏览器反检测**:

```python
browser = await p.chromium.launch(headless=True, args=[
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox", "--disable-dev-shm-usage",
    "--disable-web-security",
    "--disable-features=IsolateOrigins,site-per-process",
])
context = await browser.new_context(
    viewport={"width": 1920, "height": 1080},
    user_agent="Mozilla/5.0 (...Chrome/125...)",
    timezone_id="America/New_York",
)
```

---

### 3.6 列表页解析 (`list_parser.py`)

**技术**: BeautifulSoup4 + lxml

**设计思路**: 多重 CSS 选择器兜底

Amazon 的页面结构经常微调，类名可能变化。所以每个字段都准备了 4-7 种不同的选择器，按优先级从高到低尝试，第一个匹配到的有效值即为结果。

**标题解析（6 层兜底）**:

```python
title_selectors = [
    ("h2[aria-label]", "attr", "aria-label"),                  # 第1优先
    ("h2 span", "text", None),                                 # 第2优先
    ("h2", "text", None),                                      # 第3优先
    ("a.a-link-normal h2", "text", None),                      # 第4优先
    (".s-title-instructions-style h2", "text", None),          # 第5优先
    ("img.s-image[alt]", "attr", "alt"),                       # 第6优先（兜底）
]

for sel, method, attr in title_selectors:
    node = card_node.select_one(sel)
    if not node: continue
    if method == "attr":
        title = node.get(attr, "")
    else:
        title = node.get_text(strip=True)
    title = title.replace("Sponsored Ad - ", "", 1).strip()
    if title and len(title) > 5:
        break
```

**价格解析（7 层兜底 + 正则兜底）**:

```python
price_selectors = [
    'span.a-price[data-a-color="base"] .a-offscreen',
    ".a-price .a-offscreen",
    "span.a-price-whole",
    ".s-price",
    '.a-price span[aria-hidden="true"]',
    'span[data-a-color="price"]',
    'span.aok-offscreen',
]
# ...尝试每个选择器...

# 如果都不行，用正则在整个卡片文本中找 $xx.xx 模式
card_text = card_node.get_text()
m = re.search(r"\$(\d+\.\d{2})", card_text)
if m:
    return (f"${m.group(1)}", float(m.group(1)))
```

**空格数据过滤**:

```python
# 过滤掉没有标题的商品（完全没有识别意义）
if not title:
    return None
```

**去重策略**:

```python
# 同 ASIN 保留字段填充最多的版本
product_map = {}
for p in all_products:
    asin = p["asin"]
    if asin not in product_map:
        product_map[asin] = p
    else:
        old_filled = sum(1 for v in product_map[asin].values() if v is not None)
        new_filled = sum(1 for v in p.values() if v is not None)
        if new_filled > old_filled:
            product_map[asin] = p
```

---

### 3.7 详情页解析 (`detail_parser.py`)

**技术**: BeautifulSoup4 + lxml + 正则

**设计思路**: 和列表页解析一致，也为每个字段准备多个选择器。额外处理 JSON 字段（图片列表、规格表等需要序列化为字符串存入 SQLite）。

**品牌提取（含 URL 解码）**:

```python
def _extract_brand(soup):
    brand_elem = soup.select_one("#bylineInfo")
    if not brand_elem: return None
    brand_link = brand_elem.get("href", "")
    # Amazon 品牌链接格式: /browse?node=123&field-lbr_brands_browse-bin=EasySMX
    brand_match = re.search(r"field-lbr_brands_browse-bin[^&]*&[^&]*&([^&]+)", brand_link)
    if brand_match:
        return unquote(brand_match.group(1))  # URL 解码
    return brand_elem.get_text(strip=True)
```

**价格提取（7 层兜底）**:

```python
def _extract_current_price(soup):
    # 策略1: .a-offscreen（主价格）
    price_elem = soup.select_one(".a-price .a-offscreen")
    if price_elem: return _parse(price_elem.get_text(strip=True))

    # 策略2: #corePrice_desktop（新版容器）
    price_elem = soup.select_one("#corePrice_desktop .a-offscreen")
    if price_elem: return _parse(price_elem.get_text(strip=True))

    # 策略3-6: ...
    # 策略7: 正则全文搜索
    body_text = soup.get_text()
    m = re.search(r"\$(\d+\.\d{2})", body_text)
    if m: return (f"${m.group(1)}", float(m.group(1)))

    return (None, None)
```

**图片提取（缩略图→高清图）**:

```python
def _extract_images(soup):
    images = []
    thumb_imgs = soup.select("#altImages img")
    for img in thumb_imgs:
        src = img.get("src", "")
        if src and "data:image" not in src:
            # 替换缩略图后缀为高清版
            hi_res = re.sub(r"\._?[A-Za-z0-9_]+_\.", "._SL1500_.", src)
            images.append(hi_res)
    return json.dumps(images, ensure_ascii=False) if images else None
```

---

### 3.8 数据库模型 (`models.py`)

**技术**: SQLAlchemy 2.0 ORM (DeclarativeBase)

**设计思路**:
- 两张表：`products`（商品主表）和 `price_history`（价格历史）
- 所有非关键字段设为 `Optional`（可为 NULL），不因为一个字段缺失就丢整条记录
- JSON 字段（如 `bullet_points`、`images`、`specifications`）以字符串形式存储，取用时 `json.loads()`

**ER 图**:

```
products                              price_history
───────────                           ──────────────
asin (PK, VARCHAR 20)                 id (PK, INTEGER AUTO)
title (TEXT, NULL)                    asin (FK → products.asin)
keyword (VARCHAR 100, NULL)           price (FLOAT)
current_price (FLOAT, NULL)           price_raw (VARCHAR 50, NULL)
current_price_raw (VARCHAR 50, NULL)  recorded_at (DATETIME)
list_price_raw (VARCHAR 50, NULL)
rating (FLOAT, NULL)
review_count (INTEGER, NULL)
brand (VARCHAR 200, NULL)
bullet_points (TEXT, NULL)    ← JSON 字符串
specifications (TEXT, NULL)   ← JSON 字符串
images (TEXT, NULL)           ← JSON 字符串
card_type (VARCHAR 50, NULL)
detail_fetched (BOOLEAN, DEFAULT FALSE)
created_at (DATETIME)
updated_at (DATETIME)
```

**关键设计决策**:

| 决策 | 原因 |
|------|------|
| 用 `None` 表示缺失字段 | 区分"未采集"和"字段值为空"，统计完整度时 `is not None` 即可 |
| JSON 字段存字符串 | SQLite 不支持嵌套类型，字符串最通用；`ensure_ascii=False` 保留中文 |
| `list_price_raw` 只存原始文本 | 标注价经常是多货币格式（"$35.99"），统一存文本，需要时再解析 |
| `detail_fetched` 标记 | 区分"还没采详情"和"采了但没拿到数据" |

---

### 3.9 数据仓库 (`repository.py`)

**技术**: SQLAlchemy ORM + Repository 模式

**设计思路**: Repository 模式封装所有数据库操作，上层代码（路由、CLI）不直接操作 SQLAlchemy。

**核心方法**:

```python
class ProductRepository:
    def upsert_product(self, data: dict) -> Product:
        """按 ASIN 更新或插入，只覆盖非 None 字段"""
        product = self.db.query(Product).filter(Product.asin == asin).first()
        if product:
            for key, value in data.items():
                if value is not None and hasattr(product, key):
                    setattr(product, key, value)
        else:
            product = Product(**data)
            self.db.add(product)
        ...

    def record_price(self, asin: str, price: float, ...) -> PriceHistory | None:
        """记录价格快照，变化超过 50% 跳过（防异常数据污染）"""
        last = self.db.query(PriceHistory)...first()
        if last and last.price == price: return None  # 未变

        if last and abs(price - last.price) / last.price * 100 > 50:
            logger.warning(f"ASIN {asin}: 价格异常变化 {change_pct:.0f}%，跳过")
            return None  # 跳过异常数据
        ...

    def get_price_drops(self, min_pct: float = 5.0) -> list[dict]:
        """检测降价商品（对比 price_history 最新两条记录）"""

    def get_filter_options(self) -> dict:
        """获取分类/品类/价格状态等过滤选项和计数"""
```

**upsert 的"只覆盖非 None"设计**:

```python
for key, value in data.items():
    if value is not None and hasattr(product, key):
        setattr(product, key, value)
```

为什么重要：详情页可能只采集到部分字段（如标题和评分，但没拿到价格），这个设计确保不会用 `None` 覆盖掉已有的正确数据。

---

### 3.10 价格监控 (`price_checker.py` + `notifier.py`)

**技术**: SQLAlchemy + httpx (Telegram API)

**价格监控流程**:

```
monitor 命令
    │
    ├── step 1: 记录快照
    │   遍历所有有价格的商品 → 当前价格写入 price_history
    │   如果价格和上次一样 → 跳过
    │   如果价格变化 > 50% → 跳过（防异常数据）
    │
    ├── step 2: 检测降价
    │   对每个商品查 price_history 最新 2 条记录
    │   如果 新价格 < 旧价格 → 计算降幅百分比
    │
    └── step 3: 推送通知（可选）
        if drops and --notify:
            Telegram Bot 发送消息
            或 控制台打印
```

**通知器设计（策略模式）**:

```python
class BaseNotifier:
    def send_price_alert(self, product: dict) -> bool: ...

class ConsoleNotifier(BaseNotifier):  # 控制台输出
    def send_price_alert(self, product):
        print(f"📉 {product['title']}: ${product['old_price']} → ${product['new_price']}")

class TelegramNotifier(BaseNotifier):  # Telegram Bot
    def send_price_alert(self, product):
        httpx.post(f"{API_BASE}/sendMessage", json={
            "chat_id": self.chat_id,
            "text": f"📉 <b>降价!</b> ...",
            "parse_mode": "HTML",
        })

def get_notifier() -> BaseNotifier:
    """优先 Telegram，否则控制台"""
    telegram = TelegramNotifier()
    return telegram if telegram.is_configured else ConsoleNotifier()
```

---

### 3.11 Web 服务 (`routes.py` + `templates/`)

**技术**: FastAPI + Jinja2 + Bootstrap 5 + ECharts (CDN)

**路由设计**:

| 路由 | 功能 | 模板 |
|------|------|------|
| `GET /` | Dashboard 首页 | `dashboard.html` |
| `GET /product/{asin}` | 商品详情 + 价格走势图 | `product.html` |
| `GET /api/products` | 商品列表 JSON API | — |
| `GET /api/product/{asin}/price-history` | 价格历史 JSON API | — |
| `GET /api/stats` | 统计数据 JSON API | — |

**Dashboard 路由核心逻辑**:

```python
@router.get("/", response_class=HTMLResponse)
async def dashboard(request, page, sort_by, order, keyword, card_type, price_status, category):
    with ProductRepository() as repo:
        stats = repo.get_stats()                    # 统计卡片
        products, total = repo.list_all(            # 商品列表（分页）
            page=page, search=keyword,
            card_type=card_type, category=category,
        )
        drops = repo.get_price_drops(min_pct=0)     # 降价商品
        filter_opts = repo.get_filter_options()     # 过滤选项

    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": stats, "products": products, ...
    })
```

**价格走势图 (ECharts)**:

前端使用 ECharts 折线图展示价格变化，从 `/api/product/{asin}/price-history` 获取数据。markPoint 标注最高价和最低价。

```javascript
// product.html 中的关键 JS
var chart = echarts.init(document.getElementById('price-chart'));
chart.setOption({
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value', name: 'Price (USD)' },
    series: [{
        type: 'line', data: prices, smooth: true,
        markPoint: {
            data: [
                { type: 'min', name: 'Lowest' },
                { type: 'max', name: 'Highest' }
            ]
        }
    }]
});
```

---

### 3.12 CLI 入口 (`main.py`)

**技术**: click

**设计思路**: 四个子命令，覆盖完整工作流

| 命令 | 功能 | 典型用法 |
|------|------|---------|
| `crawl` | 采集数据 | `python main.py crawl --all` |
| `monitor` | 价格监控 | `python main.py monitor --notify` |
| `web` | Web Dashboard | `python main.py web` |
| `schedule` | 定时调度 | `python main.py schedule` |
| `cleanup` | 清理空数据 | `python main.py cleanup` |

**crawl 命令的内部流程**:

```python
def crawl(keyword, pages, concurrency, all_keywords, force_details):
    # Step 1: 列表页采集
    遍历关键词列表 →
        crawl_all_keywords()           # 所有关键词的列表页
        parse_raw_data(raw_data)       # 解析原始 HTML
        for p in products: p["keyword"] = kw  # 标记品类
        repo.bulk_upsert_products()    # 入库

    # Step 2: 详情页采集
    pending_asins = 取未采集的 ASIN 列表
    if force_details: 取全部 ASIN
    asyncio.run(crawl_detail_pages(pending_asins))
    for result in results:
        parse_detail_page(asin, html)  # 解析详情
        repo.upsert_product(detail)    # 补充入库
```

---

## 4. 核心设计模式

### 4.1 流水线模式

三个阶段串行，数据逐级流转：

```
采集 → 解析 → 存储
```

每阶段职责单一：
- **采集层**：只负责获取原始 HTML，不关心内容
- **解析层**：只负责提取结构化数据，不关心存储
- **存储层**：只负责持久化，不关心数据来源

### 4.2 多重兜底策略

每个字段准备 4-7 种不同的选择器，按优先级尝试：

```python
title = None
for selector in [优先级1, 优先级2, ..., 优先级7]:
    node = card.select_one(selector)
    if node:
        title = extract(node)
        if title and len(title) > 5:
            break
```

### 4.3 断点续爬

```python
# 加载已有数据，跳过已完成的 ASIN
try:
    with open(OUTPUT_JSON, "r") as f:
        existing = json.load(f)
    done_asins = {p["asin"] for p in existing}
except FileNotFoundError:
    done_asins = set()

for asin in asins:
    if asin in done_asins:
        continue  # 跳过
    # ...采集逻辑...
```

现在用数据库的 `detail_fetched` 字段实现同样的效果。

### 4.4 Repository 模式

所有数据库操作集中在 `repository.py`，上层代码不直接写 SQL 或 ORM 查询：

```python
# ✅ 好：通过 Repository 操作
with ProductRepository() as repo:
    repo.upsert_product(data)
    products = repo.list_all(page=1)

# ❌ 不好：直接操作 SQLAlchemy
db.query(Product).filter(...).all()
```

### 4.5 全局单例 (config/logger/settings)

```python
# config.py
settings = Settings.from_yaml()  # 在模块加载时初始化

# 其他文件直接引用
from app.config import settings
from app.logger import logger
```

---

## 5. 反爬策略技术详解

### 5.1 Amazon 的五层反爬体系

| 层次 | 检测内容 | 本项目对策 |
|------|---------|-----------|
| **L1 TLS 指纹** | JA3/JA4 指纹，检测客户端库特征 | `curl_cffi impersonate="chrome120"` 模拟 Chrome 完整 TLS 握手 |
| **L2 HTTP/2 帧** | SETTINGS 帧、WINDOW_UPDATE 等参数 | curl_cffi 自动处理 |
| **L3 WAF Token** | aws-waf-token 验证 | Cookie 管理器自动获取，支持手动兜底 |
| **L4 行为分析** | 请求频率、间隔、Referer 链、鼠标轨迹 | 随机延迟 2-4s + 完整 Referer 链 |
| **L5 静默 CAPTCHA** | 返回 200 但实际是验证页 | Playwright 渲染 + 内容长度/关键词检测 |

### 5.2 curl_cffi 的工作原理

Python 标准 `requests` 库使用 urllib3，其 TLS 握手参数与真实浏览器差异明显（如 cipher suites 顺序、ALPN 扩展、HTTP/2 SETTINGS 帧的初始值）。Amazon 的 WAF 通过 JA3 算法计算 TLS 握手指纹，能轻易识别出非浏览器流量。

`curl_cffi` 底层调用 libcurl，并提供了 `impersonate` 参数，直接使用 Chrome/Firefox 等真实浏览器的 TLS 配置文件和 HTTP/2 参数，使 WAF 难以区分。

```python
# requests 的指纹：易被识别
response = requests.post(url, headers=headers, cookies=cookies)

# curl_cffi 的指纹：模拟 Chrome
response = cffi_requests.post(url, headers=headers, cookies=cookies,
                               impersonate="chrome120")
```

### 5.3 Playwright 反检测

Playwright 默认的 headless 模式有可检测的特征（如 `navigator.webdriver` 为 `true`）。需要手动隐藏：

```python
# 1. 启动参数
args = [
    "--disable-blink-features=AutomationControlled",  # 隐藏自动化标记
    "--no-sandbox",
    "--disable-web-security",
]

# 2. 注入脚本移除 webdriver 属性
page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5]
    });
""")

# 3. 使用真实浏览器的 User-Agent
context = browser.new_context(
    user_agent="Mozilla/5.0 (...Chrome/125.0.0.0 Safari/537.36)",
    locale="en-US",
)
```

---

## 6. 数据库设计

### 6.1 ER 图

```
┌─────────────────────────────┐       ┌──────────────────────────┐
│         products            │       │      price_history       │
├─────────────────────────────┤       ├──────────────────────────┤
│ asin           VARCHAR PK   │──┐    │ id            INTEGER PK │
│ card_type      VARCHAR      │  │    │ asin          VARCHAR FK │──┐
│ keyword        VARCHAR      │  │    │ price         FLOAT      │  │
│ title          TEXT         │  │    │ price_raw     VARCHAR    │  │
│ current_price  FLOAT        │  │    │ recorded_at   DATETIME   │  │
│ current_price_raw VARCHAR   │  │    └──────────────────────────┘  │
│ list_price_raw VARCHAR      │  │                                  │
│ rating         FLOAT        │  └──────────────────────────────────┘
│ review_count   INTEGER      │
│ brand          VARCHAR      │
│ bullet_points  TEXT         │  ← JSON
│ specifications TEXT         │  ← JSON
│ images         TEXT         │  ← JSON
│ detail_fetched BOOLEAN     │
│ created_at     DATETIME    │
│ updated_at     DATETIME    │
└─────────────────────────────┘
```

### 6.2 字段设计原则

1. **宁可存 None，不存空字符串** — `None` 能正确表示"缺失"，`""` 则模棱两可
2. **JSON 字段存文本** — SQLite 不支持嵌套，用 `json.dumps` 序列化后存 TEXT
3. **原始文本 + 数值双字段** — `current_price_raw` 存 `"$32.39"`，`current_price` 存 `32.39`
4. **冗余的 `detail_fetched`** — 避免每次都去查关联表判断"是否已采集详情"

---

## 7. 如何移植到其他网站

如果你想用本项目架构抓取其他网站（天猫、京东、eBay 等），按以下步骤：

### 7.1 需要改的文件

| 文件 | 改动内容 |
|------|---------|
| `config.yaml` | 修改关键词、域名、请求延迟 |
| `app/crawler/list_crawler.py` | 修改 URL、请求参数、headers |
| `app/crawler/detail_crawler.py` | 修改 URL 模板（如 `/item/{id}`） |
| `app/parser/list_parser.py` | 替换所有 CSS 选择器为目标网站的 |
| `app/parser/detail_parser.py` | 替换详情页字段的提取逻辑 |
| `app/storage/models.py` | 按需增删字段 |

### 7.2 不需要改的文件

| 文件 | 原因 |
|------|------|
| `cookie_manager.py` | Cookie 获取方式通用（Playwright 打开任意网站都能拿到 Cookie） |
| `database.py` | SQLite 引擎配置通用 |
| `repository.py` | CRUD 操作通用（ORM 映射自动适配） |
| `config.py` | 配置加载方式通用 |
| `logger.py` | 日志配置通用 |
| `main.py` | CLI 结构通用（只是命令内部调用的函数变了） |

### 7.3 移植步骤示例

假设要抓取天猫店铺的商品：

```python
# list_crawler.py — 修改 URL 和参数
def crawl_list_page(seller_id, page_num):
    response = cffi_requests.get(
        f"https://shop.taobao.com/search.htm?pageNo={page_num}&userId={seller_id}",
        impersonate="chrome120",
    )
    return response.text

# list_parser.py — 替换选择器
def _extract_title(card_node):
    selectors = [
        ".item-title",         # 天猫类名
        ".J_ClickStat a",      # 淘宝旧版
        "a[title]",            # 通用
    ]
    ...

# detail_parser.py — 替换详情页字段
_ = soup.select_one(".tb-detail-hd")  # 天猫详情页标题
```

---

## 8. 常见问题排查

### Cookie 获取失败

```
INFO | 正在自动获取 Amazon Cookie...
INFO | 获取到 0 个 Cookie
```

**原因**: Amazon WAF 检测到 Playwright 无头浏览器并拦截。

**解决**:
1. 手动获取 Cookie：浏览器 F12 → Application → Cookies → 复制到 `cookies_manual.json`
2. 重试运行即可

### 列表页 503

```
WARNING | 列表页返回非 200: keyword=xxx, page=1, status=503
```

**原因**: Cookie 过期或 TLS 指纹被检测。

**解决**:
1. 重新获取 Cookie（删除 `data/cookies.json` 缓存）
2. 如果持续 503，降低请求频率（`config.yaml` 增大 `request_delay_*`）
3. 检查 `cookies_manual.json` 是否过期

### 详情页 5539 字符

```
WARNING | ASIN B0XXX: 被 WAF 拦截 (5539 字符)
```

**原因**: Amazon WAF 返回验证页面。

**解决**:
1. 降低并发数（`detail_concurrency: 2-3`）
2. 加手动 Cookie
3. 接受这个限制 — 5539 页面中仍有部分数据可提取

### 价格异常（突然降 80%+）

```
📉 $100.00 → $15.00 (-85%)
```

**原因**: 详情页采集到了错误价格（如标注价而不是售价）。

**解决**:
1. 系统已自动跳过变化超过 50% 的记录（`record_price` 中的阈值检查）
2. 清除错误历史：`python -c "from app.storage.database import *; SessionLocal().query(PriceHistory).delete(); SessionLocal().commit()"`
3. 重新跑 `python main.py monitor`

---

## 附录：技术栈速查

| 技术 | 用途 | 学习文档 |
|------|------|---------|
| Python 3.12+ | 主语言 | [python.org](https://docs.python.org/3/) |
| curl_cffi | TLS 指纹模拟 | [github.com/yifeikong/curl_cffi](https://github.com/yifeikong/curl_cffi) |
| Playwright | 浏览器自动化 | [playwright.dev/python](https://playwright.dev/python/) |
| BeautifulSoup4 | HTML 解析 | [crummy.com](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) |
| SQLAlchemy 2.0 | ORM | [sqlalchemy.org](https://docs.sqlalchemy.org/en/20/) |
| FastAPI | Web 框架 | [fastapi.tiangolo.com](https://fastapi.tiangolo.com/) |
| ECharts | 图表 | [echarts.apache.org](https://echarts.apache.org/en/index.html) |
| Docker | 容器化 | [docs.docker.com](https://docs.docker.com/) |
| loguru | 日志 | [loguru.readthedocs.io](https://loguru.readthedocs.io/) |
| click | CLI | [click.palletsprojects.com](https://click.palletsprojects.com/) |
