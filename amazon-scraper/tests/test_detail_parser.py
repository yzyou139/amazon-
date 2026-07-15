"""详情页解析器单元测试"""

import json

import pytest

from app.parser.detail_parser import (
    parse_detail_page,
    _extract_brand,
    _extract_current_price,
    _extract_bullet_points,
    _extract_images,
)

# ========== HTML Fixtures ==========

SAMPLE_DETAIL_HTML = """
<html>
<body>
    <span id="productTitle">EasySMX X15 Wireless Gaming Controller</span>

    <a id="bylineInfo" href="/browse?node=123&field-lbr_brands_browse-bin=EasySMX">Visit the EasySMX Store</a>

    <span class="a-price">
        <span class="a-offscreen">$32.39</span>
        <span class="a-price-whole">32</span>
        <span class="a-price-fraction">39</span>
        <span class="a-price-symbol">$</span>
    </span>

    <span class="a-text-price"><span class="a-offscreen">$35.99</span></span>

    <div id="feature-bullets">
        <li><span>Wireless Connection</span></li>
        <li><span>Ergonomic Design</span></li>
        <li><span>Long Battery Life</span></li>
    </div>

    <div id="altImages">
        <img src="https://example.com/img1._AC_US40_.jpg">
        <img src="https://example.com/img2._AC_US40_.jpg">
    </div>

    <span data-hook="rating-out-of-text">4.2 out of 5</span>
    <span data-hook="total-review-count">2,776 total ratings</span>

    <div id="availability"><span>In Stock</span></div>

    <div id="productDetails_techSpec_section_1">
        <table>
            <tr><th>Brand</th><td>EasySMX</td></tr>
            <tr><th>Color</th><td>Black</td></tr>
        </table>
    </div>
</body>
</html>
"""


class TestParseDetailPage:
    def test_basic_fields(self):
        detail = parse_detail_page("B0CSFW3465", SAMPLE_DETAIL_HTML)
        assert detail["asin"] == "B0CSFW3465"
        assert detail["title"] == "EasySMX X15 Wireless Gaming Controller"
        assert detail["current_price"] == 32.39
        assert detail["current_price_raw"] == "$32.39"
        assert detail["list_price_raw"] == "$35.99"
        assert detail["rating"] == 4.2
        assert detail["review_count"] == 2776
        assert detail["in_stock"] == "In Stock"
        assert detail["detail_fetched"] is True

    def test_bullet_points(self):
        detail = parse_detail_page("B0CSFW3465", SAMPLE_DETAIL_HTML)
        bullets = json.loads(detail["bullet_points"])
        assert len(bullets) == 3
        assert "Wireless Connection" in bullets

    def test_images(self):
        detail = parse_detail_page("B0CSFW3465", SAMPLE_DETAIL_HTML)
        images = json.loads(detail["images"])
        assert len(images) == 2
        # 应该被替换为高清版本
        assert "_SL1500_" in images[0]

    def test_specifications(self):
        detail = parse_detail_page("B0CSFW3465", SAMPLE_DETAIL_HTML)
        specs = json.loads(detail["specifications"])
        assert specs["Brand"] == "EasySMX"
        assert specs["Color"] == "Black"
