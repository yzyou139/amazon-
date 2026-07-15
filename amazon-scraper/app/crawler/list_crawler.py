"""列表页采集器 — 使用 curl_cffi 模拟浏览器 TLS 指纹"""

import random
import time
from typing import Optional

from curl_cffi import requests as cffi_requests

from app.config import settings
from app.crawler.cookie_manager import cookie_manager
from app.logger import logger

# ========== 常量 ==========
BASE_URL = "https://www.amazon.com/s/query"
SEARCH_URL = "https://www.amazon.com/s"

HEADERS = {
    "accept": "text/html,image/webp,*/*",
    "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "cache-control": "no-cache",
    "content-type": "application/json",
    "device-memory": "8",
    "downlink": "10",
    "dpr": "1",
    "ect": "4g",
    "origin": "https://www.amazon.com",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "rtt": "50",
    "sec-ch-device-memory": "8",
    "sec-ch-dpr": "1",
    "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"10.0.0"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "viewport-width": "1920",
    "x-requested-with": "XMLHttpRequest",
}


def _build_params(keyword: str, page_num: int) -> dict:
    """构建搜索请求参数"""
    # 用关键词生成一个固定的 qid（模拟真实搜索）
    qid = str(hash(keyword) % 10**13)

    return {
        "k": keyword,
        "page": str(page_num),
        "qid": qid,
        "ref": f"sr_pg_{page_num}",
        "sprefix": f"{keyword[:5]}%2Caps%2C300",
        "xpid": f"x{random.randint(1000, 9999)}x{random.randint(100, 999)}",
    }


def crawl_list_page(keyword: str, page_num: int, cookies: dict | None = None) -> Optional[str]:
    """
    爬取单页亚马逊搜索结果。

    Args:
        keyword: 搜索关键词
        page_num: 页码 (从 1 开始)
        cookies: Cookie 字典（None 则自动获取）

    Returns:
        原始响应文本，失败返回 None
    """
    if cookies is None:
        cookies = cookie_manager.get_cookies()

    params = _build_params(keyword, page_num)

    # 更新 referer
    headers = dict(HEADERS)
    if page_num > 1:
        headers["referer"] = (
            f"https://www.amazon.com/s?k={keyword}&page={page_num - 1}&qid={params['qid']}"
        )
        headers["x-amazon-s-fallback-url"] = (
            f"https://www.amazon.com/s?k={keyword}&qid={params['qid']}&ref=sr_pg_{page_num}"
        )

    json_data = {"customer-action": "pagination"}

    try:
        response = cffi_requests.post(
            BASE_URL,
            params=params,
            cookies=cookies,
            headers=headers,
            json=json_data,
            impersonate=settings.impersonate_target,
            timeout=settings.page_timeout,
        )

        if response.status_code != 200:
            logger.warning(
                f"列表页返回非 200: keyword={keyword}, page={page_num}, "
                f"status={response.status_code}"
            )
            return None

        raw_text = response.text

        # 检查是否触发验证码
        if len(raw_text) < 500 or "Robot Check" in raw_text or "captcha" in raw_text.lower():
            logger.warning(f"列表页疑似触发验证码: keyword={keyword}, page={page_num}")
            return None

        logger.info(
            f"列表页成功: keyword={keyword}, page={page_num}, "
            f"数据长度={len(raw_text):,} 字符"
        )
        return raw_text

    except Exception as e:
        logger.error(f"列表页异常: keyword={keyword}, page={page_num} — {e}")
        return None


def crawl_list_pages_for_keyword(keyword: str, max_pages: int | None = None) -> dict[str, str]:
    """
    采集一个关键词的多页搜索结果。

    Args:
        keyword: 搜索关键词
        max_pages: 最大页数（None 使用配置值）

    Returns:
        {页码(str): 原始HTML} 字典
    """
    if max_pages is None:
        max_pages = settings.max_list_pages

    # 确保有有效 Cookie
    cookies = cookie_manager.get_cookies()

    results = {}
    consecutive_failures = 0

    for page in range(1, max_pages + 1):
        page_data = crawl_list_page(keyword, page, cookies)
        if page_data:
            results[str(page)] = page_data
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= 2:
                logger.warning(f"连续 {consecutive_failures} 次失败，停止采集: keyword={keyword}")
                break

        # 页间延迟
        if page < max_pages:
            delay = random.uniform(*settings.request_delay)
            logger.debug(f"等待 {delay:.1f}s...")
            time.sleep(delay)

    logger.info(f"关键词 '{keyword}' 采集完成: {len(results)}/{max_pages} 页有效")
    return results


def crawl_all_keywords() -> dict[str, dict[str, str]]:
    """
    采集所有配置中的关键词。

    Returns:
        {keyword: {页码: 原始HTML}}
    """
    all_data = {}
    for kw in settings.keywords:
        logger.info(f"===== 开始采集关键词: {kw} =====")
        all_data[kw] = crawl_list_pages_for_keyword(kw)
    return all_data
