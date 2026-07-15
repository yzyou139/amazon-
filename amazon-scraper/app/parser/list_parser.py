"""列表页 HTML 解析器 — 从 Amazon 搜索结果页提取商品信息

保留原有 4-6 层 CSS 选择器兜底策略，适配项目级架构。
"""

import json
import re
from typing import Optional

import html as html_lib
from bs4 import BeautifulSoup, Tag

from app.logger import logger


def _extract_title(card_node: Tag) -> Optional[str]:
    """提取商品标题（6 层兜底）"""
    title = None
    title_selectors = [
        ("h2[aria-label]", "attr", "aria-label"),
        ("h2 span", "text", None),
        ("h2", "text", None),
        ("a.a-link-normal h2", "text", None),
        (".s-title-instructions-style h2", "text", None),
        ("img.s-image[alt]", "attr", "alt"),
    ]

    for sel, method, attr in title_selectors:
        node = card_node.select_one(sel)
        if not node:
            continue
        if method == "attr" and attr:
            title = node.get(attr, "")
        else:
            title = node.get_text(strip=True)

        title = title.replace("Sponsored Ad - ", "", 1).strip()
        if title and len(title) > 5:
            break

    return html_lib.unescape(title) if title else None


def _extract_price(card_node: Tag) -> tuple[Optional[str], Optional[float]]:
    """提取当前售价（7 层兜底）返回 (原始文本, 数值)"""
    price_selectors = [
        'span.a-price[data-a-color="base"] .a-offscreen',
        ".a-price .a-offscreen",
        "span.a-price-whole",
        ".s-price",
        '.a-price span[aria-hidden="true"]',
        'span[data-a-color="price"]',
        'span.aok-offscreen',
    ]

    for sel in price_selectors:
        node = card_node.select_one(sel)
        if not node:
            continue
        text = node.get_text(strip=True)
        if re.search(r"\$\d+\.?\d*", text) or re.search(r"\d+\.\d{2}", text):
            num_m = re.search(r"[\d.]+", text.replace(",", ""))
            return (text, float(num_m.group()) if num_m else None)

    # 兜底: 全文搜索 $xx.xx 模式
    card_text = card_node.get_text()
    m = re.search(r"\$(\d+\.\d{2})", card_text)
    if m:
        return (f"${m.group(1)}", float(m.group(1)))

    return (None, None)

    return (None, None)


def _extract_list_price(card_node: Tag) -> Optional[str]:
    """提取划线原价"""
    list_selectors = [
        "span.a-price.a-text-price .a-offscreen",
        ".a-text-strike .a-offscreen",
        "span[data-a-strike='true']",
        ".a-price[data-a-color='secondary'] .a-offscreen",
    ]
    for sel in list_selectors:
        node = card_node.select_one(sel)
        if node:
            return node.get_text(strip=True)
    return None


def _extract_rating(card_node: Tag) -> Optional[float]:
    """提取星级评分（5 层兜底）"""
    # 第1-2层：aria-label 匹配
    for rt in card_node.select("[aria-label*='out of 5 stars']"):
        m = re.search(r"(\d+\.?\d*) out of 5 stars", rt["aria-label"])
        if m:
            return float(m.group(1))

    # 第3层：a-icon-alt
    icon = card_node.select_one("span.a-icon-alt")
    if icon:
        m = re.search(r"(\d+\.?\d*) out of 5 stars", icon.text)
        if m:
            return float(m.group(1))

    # 第4层：纯数字 span
    for span in card_node.select("span.a-size-small.a-color-base"):
        t = span.get_text(strip=True)
        if re.match(r"^\d\.\d$", t):
            return float(t)

    return None


def _extract_review_count(card_node: Tag) -> tuple[Optional[str], Optional[int]]:
    """提取评价总数，返回 (原始文本, 数值)"""
    review_raw = None
    review_num = None

    # 第1层：aria-label
    review_a = card_node.select_one("a[aria-label*='ratings']")
    if review_a and review_a.get("aria-label"):
        m = re.search(r"([\d,]+) ratings", review_a["aria-label"])
        if m:
            review_raw = m.group(1)
            review_num = int(review_raw.replace(",", ""))

    # 第2层：customerReviews 链接
    if not review_raw:
        review_span = card_node.select_one("a[href*='customerReviews'] span")
        if review_span:
            review_raw = review_span.get_text(strip=True).strip("()")

    # 第3层：泛化匹配
    if not review_raw:
        for s in card_node.select("span.a-size-mini, span.a-size-small"):
            t = s.get_text(strip=True).strip("()")
            if re.match(r"^[\d,.]+[KM]?$", t) and len(t) <= 10:
                review_raw = t
                break

    # 解析数值
    if review_raw and not review_num:
        text = review_raw
        if text.endswith("K"):
            review_num = int(float(text[:-1]) * 1000)
        elif text.endswith("M"):
            review_num = int(float(text[:-1]) * 1_000_000)
        elif text.replace(",", "").isdigit():
            review_num = int(text.replace(",", ""))

    return (review_raw, review_num)


def _extract_delivery(card_node: Tag) -> Optional[str]:
    """提取配送信息"""
    for sel in [".udm-primary-delivery-message", ".delivery-message", "#deliveryBlockMessage"]:
        node = card_node.select_one(sel)
        if node:
            return node.get_text(" ", strip=True)
    return None


def _extract_image(card_node: Tag) -> Optional[str]:
    """提取商品主图"""
    img = card_node.select_one("img.s-image")
    return img["src"] if img and img.get("src") else None


def parse_single_product(
    card_node: Tag,
    card_type: str = "未知",
    fallback_asin: str | None = None,
    keyword: str | None = None,
) -> Optional[dict]:
    """解析单个商品卡片，返回字段字典或 None"""
    # === ASIN 三层提取 ===
    asin = None
    if card_node.get("data-asin"):
        asin = card_node["data-asin"].strip()
    if not asin:
        asin_tag = card_node.select_one("[data-asin]")
        if asin_tag:
            asin = asin_tag["data-asin"].strip()
    if not asin and fallback_asin:
        asin = fallback_asin.strip()

    if not asin or len(asin) != 10 or not asin.isalnum():
        return None

    # === 提取各字段 ===
    current_price_raw, current_price = _extract_price(card_node)
    review_count_raw, review_count = _extract_review_count(card_node)
    sales = card_node.find(string=re.compile(r"bought in past month"))
    title = _extract_title(card_node)
    rating = _extract_rating(card_node)

    # 过滤掉无标题的垃圾数据（没有标题的商品没有任何识别意义）
    if not title:
        return None

    list_price_raw = _extract_list_price(card_node)
    delivery_info = _extract_delivery(card_node)
    image_url = _extract_image(card_node)

    return {
        "asin": asin,
        "card_type": card_type,
        "keyword": keyword,
        "title": title,
        "current_price_raw": current_price_raw,
        "current_price": current_price,
        "list_price_raw": list_price_raw,
        "rating": rating,
        "review_count": review_count,
        "monthly_sales": sales.strip() if sales else None,
        "delivery_info": delivery_info,
        "image_url": image_url,
    }


def parse_list_html(
    html_content: str,
    slot_name: str = "",
    fallback_asin: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    """
    解析列表页 HTML 片段，提取所有商品卡片。

    Args:
        html_content: 原始 HTML 文本
        slot_name: dispatch 槽位名称（用于卡片类型判定）
        fallback_asin: 备用 ASIN
        keyword: 搜索关键词（mouse/手柄等）

    Returns:
        商品字典列表（已去重）
    """
    soup = BeautifulSoup(html_content, "lxml")
    products = []
    seen = set()

    all_asin_nodes = soup.select("[data-asin]")

    for node in all_asin_nodes:
        asin = node.get("data-asin", "").strip()
        if not asin or len(asin) != 10 or not asin.isalnum() or asin in seen:
            continue

        # 判断卡片类型
        card_type = "其他"
        if node.get("data-component-type") == "s-search-result":
            card_type = "主搜索结果"
        elif node.find_parent("li.a-carousel-card"):
            card_type = "轮播推荐"
        elif "AdHolder" in node.get("class", []):
            card_type = "广告位"
        elif slot_name.startswith("data-main-slot:"):
            card_type = "主搜索结果"

        product = parse_single_product(node, card_type, fallback_asin, keyword)
        if product and product["asin"]:
            products.append(product)
            seen.add(asin)

    return products


def parse_raw_data(raw_data: dict, separator: str = "&&&") -> list[dict]:
    """
    解析原始采集数据（amazon_raw_data.json 格式）。

    Amazon 返回的原始数据用 &&& 分隔多个 dispatch 片段，
    每个片段是一个 JSON 数组: [null, "slot_name", {"html": "...", "asin": "..."}]

    Args:
        raw_data: {page_num: raw_text} 格式的原始数据
        separator: dispatch 分隔符

    Returns:
        解析后的商品列表（已去重）
    """
    all_products = []
    stats = {"fragments": 0, "json_fail": 0, "no_html": 0, "has_product": 0}

    for page_key, page_content in raw_data.items():
        logger.debug(f"解析页码: {page_key}")

        fragments = page_content.split(separator)
        valid_fragments = [f for f in fragments if f.strip()]
        stats["fragments"] += len(valid_fragments)

        for frag in valid_fragments:
            frag = frag.strip()

            # 解析 dispatch JSON
            try:
                dispatch = json.loads(frag)
            except json.JSONDecodeError:
                stats["json_fail"] += 1
                continue

            slot_name = dispatch[1] if len(dispatch) > 1 else "unknown"

            html_content = ""
            top_asin = None
            if len(dispatch) >= 3 and isinstance(dispatch[2], dict):
                html_content = dispatch[2].get("html", "")
                top_asin = dispatch[2].get("asin", None)

            if not html_content or len(html_content) < 50:
                stats["no_html"] += 1
                continue

            products = parse_list_html(html_content, slot_name, top_asin)
            if products:
                stats["has_product"] += 1
                all_products.extend(products)

    # 全局去重（保留字段最完整的版本）
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

    final = list(product_map.values())

    # 字段完整度统计
    if final:
        logger.info(f"列表解析完成: {stats['fragments']} 片段 → {len(final)} 唯一商品")
        for k in final[0].keys():
            filled = sum(1 for p in final if p[k] is not None)
            logger.debug(f"  {k}: {filled}/{len(final)} ({filled / len(final) * 100:.0f}%)")

    return final
