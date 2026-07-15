"""详情页 HTML 解析器 — 从 Amazon 商品详情页提取完整信息

保留原有的多重 CSS 选择器兜底策略。
"""

import json
import re
from typing import Dict, List, Optional
from urllib.parse import unquote

from bs4 import BeautifulSoup

from app.logger import logger


def parse_detail_page(asin: str, html_text: str) -> Dict:
    """
    解析 Amazon 商品详情页 HTML，提取全部字段。

    Args:
        asin: 商品 ASIN
        html_text: 详情页完整 HTML

    Returns:
        商品详情字典
    """
    soup = BeautifulSoup(html_text, "lxml")
    detail = {"asin": asin}

    # ========== 1. 标题 ==========
    title_elem = soup.select_one("#productTitle")
    detail["title"] = title_elem.get_text(strip=True) if title_elem else None

    # ========== 2. 品牌 ==========
    detail["brand"] = _extract_brand(soup)

    # ========== 3. 当前售价 ==========
    price_text, price_num = _extract_current_price(soup)
    detail["current_price_raw"] = price_text
    detail["current_price"] = price_num

    # ========== 4. 划线原价 ==========
    list_price_elem = soup.select_one(".a-text-price .a-offscreen")
    detail["list_price_raw"] = list_price_elem.get_text(strip=True) if list_price_elem else None

    # ========== 5. 五点描述 ==========
    detail["bullet_points"] = _extract_bullet_points(soup)

    # ========== 6. 商品描述 ==========
    desc_elem = soup.select_one("#productDescription")
    detail["description"] = desc_elem.get_text(" ", strip=True) if desc_elem else None

    # ========== 7. 规格参数 ==========
    detail["specifications"] = _extract_specifications(soup)

    # ========== 8. 图片 ==========
    detail["images"] = _extract_images(soup)

    # ========== 9. 评分 ==========
    detail["rating"] = _extract_detail_rating(soup)

    # ========== 10. 评论数 ==========
    detail["review_count"] = _extract_detail_review_count(soup)

    # ========== 11. 库存状态 ==========
    avail_elem = soup.select_one("#availability span")
    detail["in_stock"] = avail_elem.get_text(strip=True) if avail_elem else None

    # ========== 12. 配送信息 ==========
    delivery_elem = soup.select_one("#mir-layout-DELIVERY_BLOCK, .delivery-message")
    detail["delivery_info"] = delivery_elem.get_text(" ", strip=True) if delivery_elem else None

    # ========== 标记详情已采集 ==========
    detail["detail_fetched"] = True

    # 统计日志
    filled = sum(1 for v in detail.values() if v is not None and (not isinstance(v, (list, dict)) or len(v) > 0))
    logger.debug(f"ASIN {asin}: 详情解析 {filled}/{len(detail)} 字段有效")

    return detail


def _extract_brand(soup: BeautifulSoup) -> Optional[str]:
    """提取品牌名"""
    brand_elem = soup.select_one("#bylineInfo")
    if not brand_elem:
        return None

    # 优先从链接中提取纯品牌名
    brand_link = brand_elem.get("href", "")
    brand_match = re.search(r"field-lbr_brands_browse-bin[^&]*&[^&]*&([^&]+)", brand_link)
    if not brand_match:
        brand_match = re.search(r"node=[^&]+&[^&]+&([^&]+)", brand_link)

    if brand_match:
        try:
            return unquote(brand_match.group(1))
        except Exception:
            pass

    return brand_elem.get_text(strip=True)


def _extract_current_price(soup: BeautifulSoup) -> tuple[Optional[str], Optional[float]]:
    """提取当前售价，返回 (原始文本, 数值) — 7 层兜底"""
    price_text = None
    price_num = None

    def _parse(text: str) -> tuple[str, float | None]:
        """从文本中解析价格"""
        m = re.search(r"\$?([\d,]+\.?\d*)", text.replace(",", ""))
        if m:
            return (text, float(m.group(1)))
        return (text, None)

    # 策略1: .a-offscreen（主价格）
    price_elem = soup.select_one(".a-price .a-offscreen")
    if price_elem:
        return _parse(price_elem.get_text(strip=True))

    # 策略2: #corePrice_desktop（Amazon 新版价格容器）
    price_elem = soup.select_one("#corePrice_desktop .a-offscreen")
    if price_elem:
        return _parse(price_elem.get_text(strip=True))

    # 策略3: #priceblock_ourprice（旧版）
    price_elem = soup.select_one("#priceblock_ourprice, #priceblock_dealprice")
    if price_elem:
        return _parse(price_elem.get_text(strip=True))

    # 策略4: .priceToPay（Amazon 特定价格类）
    price_elem = soup.select_one(".priceToPay span.a-offscreen, .priceToPay .a-price-whole")
    if price_elem:
        return _parse(price_elem.get_text(strip=True))

    # 策略5: 拼接 whole + fraction + symbol
    whole_elem = soup.select_one("span.a-price-whole")
    fraction_elem = soup.select_one("span.a-price-fraction")
    symbol_elem = soup.select_one("span.a-price-symbol")
    if whole_elem and symbol_elem:
        symbol = symbol_elem.get_text(strip=True)
        whole = whole_elem.get_text(strip=True)
        fraction = fraction_elem.get_text(strip=True) if fraction_elem else "00"
        price_text = f"{symbol}{whole}.{fraction}"
        m = re.search(r"([\d.]+)", f"{whole}.{fraction}")
        return (price_text, float(m.group(1)) if m else None)

    # 策略6: 任意 .a-price 下的 .a-offscreen（广义匹配）
    price_elem = soup.select_one("span[data-a-color='price'] .a-offscreen, .a-price span.a-offscreen")
    if price_elem:
        return _parse(price_elem.get_text(strip=True))

    # 策略7: 正则全局搜索 $xx.xx 模式
    body_text = soup.get_text()
    m = re.search(r"\$(\d+\.\d{2})", body_text)
    if m:
        return (f"${m.group(1)}", float(m.group(1)))

    return (None, None)


def _extract_bullet_points(soup: BeautifulSoup) -> Optional[str]:
    """提取五点描述，返回 JSON 字符串"""
    bullet_items = soup.select("#feature-bullets li span")
    points = [
        item.get_text(strip=True)
        for item in bullet_items
        if item.get_text(strip=True) and item.get_text(strip=True) not in ("", "：")
    ]
    return json.dumps(points, ensure_ascii=False) if points else None


def _extract_specifications(soup: BeautifulSoup) -> Optional[str]:
    """提取技术规格表，返回 JSON 字符串"""
    specs = {}
    spec_rows = soup.select(
        "#productDetails_techSpec_section_1 tr, "
        "#productDetails_detailBullets_sections1 tr, "
        "#productDetails_techSpec_section_2 tr"
    )
    for row in spec_rows:
        th = row.select_one("th")
        td = row.select_one("td")
        if th and td:
            key = th.get_text(strip=True).rstrip(":")
            value = td.get_text(strip=True)
            specs[key] = value
    return json.dumps(specs, ensure_ascii=False) if specs else None


def _extract_images(soup: BeautifulSoup) -> Optional[str]:
    """提取商品图片列表，返回 JSON 字符串"""
    images = []

    # 策略1: 缩略图容器
    thumb_imgs = soup.select("#altImages img")
    for img in thumb_imgs:
        src = img.get("src", "")
        if src and "data:image" not in src:
            # 替换为高清版本
            hi_res = re.sub(r"\._?[A-Za-z0-9_]+_\.", "._SL1500_.", src)
            images.append(hi_res)

    # 策略2: 主图兜底
    if not images:
        main_img = soup.select_one("#imgTagWrapperId img")
        if main_img and main_img.get("src"):
            images.append(main_img["src"])

    return json.dumps(images, ensure_ascii=False) if images else None


def _extract_detail_rating(soup: BeautifulSoup) -> Optional[float]:
    """提取详情页评分"""
    # 策略1: data-hook rating
    rating_elem = soup.select_one('[data-hook="rating-out-of-text"]')
    if rating_elem:
        rating_m = re.search(r"(\d+\.?\d*)", rating_elem.get_text(strip=True))
        if rating_m:
            return float(rating_m.group(1))

    # 策略2: a-icon-alt
    icon_elem = soup.select_one("span.a-icon-alt")
    if icon_elem:
        rating_m = re.search(r"(\d+\.?\d*) out of 5", icon_elem.get_text())
        if rating_m:
            return float(rating_m.group(1))

    return None


def _extract_detail_review_count(soup: BeautifulSoup) -> Optional[int]:
    """提取详情页评论数"""
    review_elem = soup.select_one('[data-hook="total-review-count"]')
    if review_elem:
        review_m = re.search(r"([\d,]+)", review_elem.get_text(strip=True))
        if review_m:
            return int(review_m.group(1).replace(",", ""))

    return None
