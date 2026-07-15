"""Cookie 自动管理器 — 使用 Playwright 获取有效 Cookie，支持缓存与手动兜底"""

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.config import settings
from app.logger import logger


class CookieManager:
    """Cookie 管理器：自动获取、缓存、验证 Amazon Cookie"""

    CACHE_FILE = Path(settings.data_dir) / "cookies.json"
    MANUAL_FILE = Path("cookies_manual.json")  # 手动 Cookie 文件
    CACHE_TTL = 3600  # 缓存有效期：1 小时

    def __init__(self):
        self._cookies: dict | None = None
        self._fetched_at: float = 0

    def get_cookies(self, force_refresh: bool = False) -> dict:
        """
        获取有效的 Cookie。
        优先级: 手动文件 > 自动缓存 > 自动获取
        """
        # 0. 检查手动 Cookie 文件（最高优先级）
        manual = self._load_manual()
        if manual and self.is_valid(manual):
            logger.info("使用手动 Cookie")
            self._cookies = manual
            self._fetched_at = time.time()
            return manual

        if not force_refresh:
            # 1. 检查内存缓存
            if self._cookies and (time.time() - self._fetched_at) < self.CACHE_TTL:
                logger.debug("使用内存缓存 Cookie")
                return self._cookies

            # 2. 检查文件缓存
            if self._load_from_file():
                logger.debug("使用文件缓存 Cookie")
                return self._cookies

        # 3. 自动获取
        logger.info("正在自动获取 Amazon Cookie...")
        try:
            cookies = self._fetch_fresh_cookies()
            if cookies:
                self._cookies = cookies
                self._fetched_at = time.time()
                self._save_to_file(cookies)
                return cookies
        except Exception as e:
            logger.warning(f"自动获取 Cookie 失败: {e}")

        # 4. 全部失败 — 提示用户手动设置
        raise RuntimeError(
            "无法获取 Amazon Cookie。\n"
            f"请创建 {self.MANUAL_FILE} 文件，内容如下：\n"
            '{"aws-waf-token": "xxx", "session-id": "xxx", "session-token": "xxx", ...}\n'
            "获取方式：浏览器打开 amazon.com → DevTools(F12) → Application → Cookies → 复制所有"
        )

    def _fetch_fresh_cookies(self) -> dict:
        """用 Playwright 打开 Amazon 首页获取 Cookie（反检测优化版）"""
        try:
            with sync_playwright() as p:
                # 启动浏览器 — 增加大量反检测参数
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-web-security",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-popup-blocking",
                    ],
                )

                # 模拟真实浏览器上下文
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    locale="en-US",
                    timezone_id="America/New_York",
                    geolocation={"latitude": 40.7128, "longitude": -74.0060},
                    permissions=["geolocation"],
                )

                # 移除 webdriver 特征
                page = context.new_page()
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                """)

                # 先访问 Amazon 首页（比直接搜素页更不容易触发 WAF）
                logger.info("访问 Amazon 首页...")
                page.goto("https://www.amazon.com", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

                # 再访问搜索页触发 aws-waf-token
                logger.info("访问搜索页...")
                page.goto("https://www.amazon.com/s?k=laptop", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)

                cookies_list = context.cookies()
                cookies = {c["name"]: c["value"] for c in cookies_list}
                logger.info(f"获取到 {len(cookies)} 个 Cookie")
                if cookies:
                    logger.debug(f"Cookie keys: {list(cookies.keys())}")
                else:
                    logger.warning("未获取到任何 Cookie — Amazon 可能拦截了无头浏览器")

                browser.close()
                return cookies

        except Exception as e:
            logger.error(f"Cookie 获取失败: {e}")
            raise RuntimeError(f"无法获取 Amazon Cookie: {e}") from e

    def is_valid(self, cookies: dict | None = None) -> bool:
        """快速验证 Cookie 是否有效（发起轻量请求测试）"""
        if cookies is None:
            cookies = self._cookies or {}

        if "aws-waf-token" not in cookies:
            return False

        try:
            from curl_cffi import requests

            resp = requests.get(
                "https://www.amazon.com/",
                cookies=cookies,
                impersonate=settings.impersonate_target,
                timeout=15,
            )
            return resp.status_code == 200 and len(resp.text) > 10000
        except Exception:
            return False

    def _load_manual(self) -> dict | None:
        """从手动 Cookie 文件加载"""
        if not self.MANUAL_FILE.exists():
            return None
        try:
            with open(self.MANUAL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data and len(data) > 3:
                logger.info(f"从 {self.MANUAL_FILE} 加载了 {len(data)} 个手动 Cookie")
                return data
        except Exception as e:
            logger.warning(f"手动 Cookie 文件读取失败: {e}")
        return None

    def _save_to_file(self, cookies: dict):
        """保存 Cookie 到文件缓存"""
        try:
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"cookies": cookies, "fetched_at": self._fetched_at},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.debug(f"Cookie 已缓存到 {self.CACHE_FILE}")
        except Exception as e:
            logger.warning(f"Cookie 缓存写入失败: {e}")

    def _load_from_file(self) -> bool:
        """从文件缓存加载 Cookie"""
        if not self.CACHE_FILE.exists():
            return False

        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            cached_at = data.get("fetched_at", 0)
            if time.time() - cached_at > self.CACHE_TTL:
                logger.debug("文件缓存 Cookie 已过期")
                return False

            cookies = data.get("cookies", {})
            if not cookies:
                return False

            if self.is_valid(cookies):
                self._cookies = cookies
                self._fetched_at = cached_at
                return True
            else:
                logger.debug("文件缓存 Cookie 无效")
                return False

        except Exception as e:
            logger.warning(f"Cookie 缓存读取失败: {e}")
            return False

    def invalidate(self):
        """使缓存失效并删除缓存文件"""
        self._cookies = None
        self._fetched_at = 0
        if self.CACHE_FILE.exists():
            self.CACHE_FILE.unlink()
        logger.info("Cookie 缓存已清除")


# 全局单例
cookie_manager = CookieManager()
