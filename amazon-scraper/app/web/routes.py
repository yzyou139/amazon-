"""Web 路由定义 — Dashboard / 商品详情 / API"""

import json
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.logger import logger
from app.storage.repository import ProductRepository

router = APIRouter()

# 模板目录
templates = Jinja2Templates(directory="app/web/templates")


# ========== 页面路由 ==========


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    page: int = Query(1, ge=1),
    sort_by: str = Query("created_at"),
    order: str = Query("desc"),
    keyword: Optional[str] = Query(None),       # 标题搜索
    card_type: Optional[str] = Query(None),      # 卡片类型
    price_status: Optional[str] = Query(None),   # "has" / "none"
    category: Optional[str] = Query(None),       # 品类 (mouse/keyboard)
):
    """仪表盘首页 — 统计卡片 + 商品列表"""
    with ProductRepository() as repo:
        stats = repo.get_stats()
        products, total = repo.list_all(
            page=page,
            per_page=20,
            sort_by=sort_by,
            order=order,
            search=keyword,
            card_type=card_type,
            price_status=price_status,
            category=category,
        )
        drops = repo.get_price_drops(min_pct=0)
        filter_opts = repo.get_filter_options()

    total_pages = max(1, (total + 19) // 20)  # 向上取整

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "products": products,
            "drops": drops,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "sort_by": sort_by,
            "order": order,
            "keyword": keyword or "",
            "card_type": card_type or "",
            "price_status": price_status or "",
            "category": category or "",
            "filter_opts": filter_opts,
        },
    )


@router.get("/product/{asin}", response_class=HTMLResponse)
async def product_detail(request: Request, asin: str):
    """商品详情页 — 基本信息 + 价格走势图"""
    with ProductRepository() as repo:
        product = repo.get_by_asin(asin)
        price_history = repo.get_price_history(asin)

    if not product:
        return HTMLResponse("<h2>商品未找到</h2>", status_code=404)

    # 准备价格走势数据
    chart_dates = [ph.recorded_at.strftime("%m-%d %H:%M") for ph in price_history]
    chart_prices = [ph.price for ph in price_history]

    # 解析 JSON 字段
    bullet_points = json.loads(product.bullet_points) if product.bullet_points else []
    specifications = json.loads(product.specifications) if product.specifications else {}
    images = json.loads(product.images) if product.images else []

    return templates.TemplateResponse(
        request,
        "product.html",
        {
            "product": product,
            "bullet_points": bullet_points,
            "specifications": specifications,
            "images": images,
            "chart_dates": chart_dates,
            "chart_prices": chart_prices,
        },
    )


# ========== API 路由 ==========


@router.get("/api/products")
async def api_products(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, le=100),
    sort_by: str = Query("created_at"),
    order: str = Query("desc"),
    keyword: Optional[str] = Query(None),
):
    """商品列表 API（JSON）"""
    with ProductRepository() as repo:
        products, total = repo.list_all(
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            order=order,
            keyword=keyword,
        )

    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "data": [
            {
                "asin": p.asin,
                "title": p.title,
                "brand": p.brand,
                "current_price": p.current_price,
                "current_price_raw": p.current_price_raw,
                "list_price_raw": p.list_price_raw,
                "rating": p.rating,
                "review_count": p.review_count,
                "image_url": p.image_url,
                "in_stock": p.in_stock,
                "card_type": p.card_type,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in products
        ],
    }


@router.get("/api/product/{asin}/price-history")
async def api_price_history(asin: str):
    """商品价格历史 API"""
    with ProductRepository() as repo:
        history = repo.get_price_history(asin)

    return {
        "asin": asin,
        "data": [
            {
                "price": h.price,
                "price_raw": h.price_raw,
                "recorded_at": h.recorded_at.isoformat(),
            }
            for h in history
        ],
    }


@router.get("/api/stats")
async def api_stats():
    """统计数据 API"""
    with ProductRepository() as repo:
        return repo.get_stats()
