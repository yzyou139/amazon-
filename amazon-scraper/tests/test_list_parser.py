"""列表页解析器单元测试"""

import pytest
from bs4 import BeautifulSoup

from app.parser.list_parser import (
    _extract_title,
    _extract_price,
    _extract_rating,
    _extract_review_count,
    parse_single_product,
    parse_list_html,
)

# ========== HTML Fixtures ==========

SAMPLE_CARD_HTML = """
<div data-asin="B0CSFW3465" data-component-type="s-search-result">
    <h2 aria-label="EasySMX X15 Wireless Gaming Controller">
        <span>EasySMX X15 Wireless Gaming Controller</span>
    </h2>
    <span class="a-price" data-a-color="base">
        <span class="a-offscreen">$32.39</span>
    </span>
    <span aria-label="4.2 out of 5 stars">
        <span class="a-icon-alt">4.2 out of 5 stars</span>
    </span>
    <a aria-label="2,776 ratings" href="#">
        <span>2,776</span>
    </a>
    <img class="s-image" src="https://example.com/img.jpg" alt="Controller Image">
    <span class="delivery-message">FREE delivery Wed, Jul 15</span>
</div>
"""


def make_card(html: str):
    soup = BeautifulSoup(html, "lxml")
    return soup.select_one("[data-asin]")


# ========== Tests ==========


class TestTitleExtraction:
    def test_h2_aria_label(self):
        card = make_card(SAMPLE_CARD_HTML)
        title = _extract_title(card)
        assert title == "EasySMX X15 Wireless Gaming Controller"

    def test_sponsored_removed(self):
        html = """
        <div data-asin="B0TEST1234">
            <h2 aria-label="Sponsored Ad - Gaming Mouse Pro">
                <span>Sponsored Ad - Gaming Mouse Pro</span>
            </h2>
        </div>
        """
        card = make_card(html)
        title = _extract_title(card)
        assert "Sponsored Ad" not in title
        assert title == "Gaming Mouse Pro"


class TestPriceExtraction:
    def test_normal_price(self):
        card = make_card(SAMPLE_CARD_HTML)
        raw, num = _extract_price(card)
        assert raw == "$32.39"
        assert num == 32.39


class TestRatingExtraction:
    def test_rating(self):
        card = make_card(SAMPLE_CARD_HTML)
        rating = _extract_rating(card)
        assert rating == 4.2


class TestReviewCount:
    def test_review_count(self):
        card = make_card(SAMPLE_CARD_HTML)
        raw, num = _extract_review_count(card)
        assert raw == "2,776"
        assert num == 2776


class TestParseSingleProduct:
    def test_full_card(self):
        card = make_card(SAMPLE_CARD_HTML)
        product = parse_single_product(card, "主搜索结果")
        assert product is not None
        assert product["asin"] == "B0CSFW3465"
        assert product["title"] == "EasySMX X15 Wireless Gaming Controller"
        assert product["current_price"] == 32.39
        assert product["rating"] == 4.2
        assert product["review_count"] == 2776
        assert product["card_type"] == "主搜索结果"

    def test_invalid_asin(self):
        html = '<div data-asin="SHORT"><h2>Test</h2></div>'
        card = make_card(html)
        product = parse_single_product(card)
        assert product is None


class TestParseListHtml:
    def test_multiple_cards(self):
        html = """
        <div>
            <div data-asin="B0CSFW3465" data-component-type="s-search-result">
                <h2 aria-label="Product A">Product A</h2>
            </div>
            <div data-asin="B0TST56789" data-component-type="s-search-result">
                <h2 aria-label="Product B">Product B</h2>
            </div>
        </div>
        """
        products = parse_list_html(html)
        assert len(products) == 2
        asins = [p["asin"] for p in products]
        assert "B0CSFW3465" in asins
        assert "B0TST56789" in asins

    def test_deduplication(self):
        html = """
        <div>
            <div data-asin="B0CSFW3465"><h2>Product A</h2></div>
            <div data-asin="B0CSFW3465"><h2>Product A Duplicate</h2></div>
        </div>
        """
        products = parse_list_html(html)
        assert len(products) == 1
