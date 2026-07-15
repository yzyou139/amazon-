"""详情页采集器 — 异步 Playwright + Semaphore 并发控制"""

import asyncio
import random
import re
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page

from app.config import settings
from app.logger import logger

MAX_RETRIES = 2
RETRY_DELAY_BASE = 8


async def _crawl_single_detail(
    asin: str,
    browser: Browser,
    semaphore: asyncio.Semaphore,
) -> tuple[str, Optional[str], Optional[Exception]]:
    """
    采集单个商品详情页的 HTML。

    Returns:
        (asin, html_text_or_None, exception_or_None)
    """
    page: Page | None = None

    async with semaphore:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                page = await browser.new_page()
                url = f"https://www.amazon.com/dp/{asin}"

                response = await page.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout * 1000)

                # 检测验证码
                page_title = await page.title()
                if re.search(r"(Robot|captcha|Enter the characters)", page_title, re.IGNORECASE):
                    logger.warning(f"ASIN {asin}: 触发验证码 (attempt {attempt}/{MAX_RETRIES})")
                    await page.close()
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(RETRY_DELAY_BASE * attempt)
                    continue

                # 等待商品标题出现（缩短超时）
                try:
                    await page.wait_for_selector("#productTitle", timeout=10000)
                except Exception:
                    pass  # 部分页面可能没有标题，继续解析

                # 短暂等待 JS 渲染完成
                await page.wait_for_timeout(500)

                html_text = await page.content()

                await page.close()
                logger.info(f"ASIN {asin}: 采集完成 ({len(html_text):,} 字符)")
                return (asin, html_text, None)

            except Exception as e:
                logger.error(f"ASIN {asin}: 异常 (attempt {attempt}/{MAX_RETRIES}) — {e}")
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if attempt < MAX_RETRIES:
                    backoff = RETRY_DELAY_BASE * attempt + random.uniform(0, 5)
                    logger.debug(f"ASIN {asin}: {backoff:.1f}s 后重试...")
                    await asyncio.sleep(backoff)

        # 所有重试都失败
        return (asin, None, Exception(f"ASIN {asin}: 所有 {MAX_RETRIES} 次重试均失败"))


async def crawl_detail_pages(
    asins: list[str],
    concurrency: int | None = None,
) -> list[tuple[str, str | None, Exception | None]]:
    """
    并发采集多个商品详情页。

    Args:
        asins: ASIN 列表
        concurrency: 并发数（None 使用配置值）

    Returns:
        [(asin, html_or_None, error_or_None), ...]
    """
    if concurrency is None:
        concurrency = settings.detail_concurrency

    if not asins:
        logger.warning("ASIN 列表为空，跳过详情采集")
        return []

    logger.info(f"开始并发采集 {len(asins)} 个 ASIN（并发数={concurrency}）")

    semaphore = asyncio.Semaphore(concurrency)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )

        # 模拟真实浏览器上下文
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )

        # 移除 WebDriver 特征
        page = await context.new_page()
        await page.add_init_script("""
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
        await page.close()

        tasks = [_crawl_single_detail(asin, browser, semaphore) for asin in asins]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        await context.close()
        await browser.close()

    # 统计
    success = sum(1 for _, html, _ in results if html is not None)
    failed = len(results) - success
    logger.info(f"详情采集完成: 成功={success}, 失败={failed}")

    if failed:
        failed_asins = [asin for asin, html, _ in results if html is None]
        logger.warning(f"失败的 ASIN: {failed_asins}")

    return results
