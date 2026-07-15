"""数据仓库层 — 封装所有 CRUD 操作"""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, desc, asc
from sqlalchemy.orm import Session

from app.logger import logger
from app.storage.database import SessionLocal
from app.storage.models import Product, PriceHistory


class ProductRepository:
    """商品数据仓库"""

    def __init__(self, db: Session | None = None):
        self.db = db or SessionLocal()
        self._own_session = db is None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._own_session:
            if exc_type:
                self.db.rollback()
            self.db.close()

    # ========== 写入操作 ==========

    def upsert_product(self, data: dict) -> Product:
        """插入或更新商品（按 ASIN 去重，新数据覆盖旧数据）"""
        asin = data.get("asin")
        if not asin:
            raise ValueError("data must contain 'asin'")

        product = self.db.query(Product).filter(Product.asin == asin).first()

        if product:
            # 更新已有记录：只覆盖非 None 字段
            for key, value in data.items():
                if value is not None and hasattr(product, key):
                    setattr(product, key, value)
            product.updated_at = datetime.now(timezone.utc)
            logger.debug(f"更新商品: {asin}")
        else:
            product = Product(**data)
            self.db.add(product)
            logger.debug(f"新增商品: {asin}")

        self.db.commit()
        self.db.refresh(product)
        return product

    def bulk_upsert_products(self, items: list[dict]) -> int:
        """批量 upsert 商品，返回新增/更新数量"""
        count = 0
        for data in items:
            try:
                self.upsert_product(data)
                count += 1
            except Exception as e:
                logger.error(f"upsert 失败: {data.get('asin', '?')} — {e}")
        self.db.commit()
        return count

    def record_price(self, asin: str, price: float, price_raw: str | None = None) -> PriceHistory | None:
        """记录价格快照（仅当价格变化合理时）"""
        # 获取最近一次记录
        last = (
            self.db.query(PriceHistory)
            .filter(PriceHistory.asin == asin)
            .order_by(desc(PriceHistory.recorded_at))
            .first()
        )

        if last and last.price == price:
            return None  # 价格未变，不记录

        # 价格合理性检查：变化超过 50% 时跳过（极大概率是采集错误）
        if last:
            change_pct = abs(price - last.price) / last.price * 100
            if change_pct > 50:
                logger.warning(
                    f"ASIN {asin}: 价格变化 {change_pct:.0f}% "
                    f"(${last.price:.2f} → ${price:.2f})，疑似异常，跳过记录"
                )
                return None

        record = PriceHistory(
            asin=asin,
            price=price,
            price_raw=price_raw,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        logger.info(f"价格记录: {asin} → ${price}")
        return record

    # ========== 查询操作 ==========

    def get_by_asin(self, asin: str) -> Product | None:
        """按 ASIN 查询"""
        return self.db.query(Product).filter(Product.asin == asin).first()

    def list_all(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "created_at",
        order: str = "desc",
        search: str | None = None,
        card_type: str | None = None,
        price_status: str | None = None,  # "has" / "none"
        category: str | None = None,  # 搜索关键词（mouse/keyboard 等）
    ) -> tuple[list[Product], int]:
        """分页查询商品列表，支持分类和价格状态过滤"""
        q = self.db.query(Product)

        if search:
            q = q.filter(Product.title.contains(search))

        if card_type:
            q = q.filter(Product.card_type == card_type)

        if price_status == "has":
            q = q.filter(Product.current_price.isnot(None))
        elif price_status == "none":
            q = q.filter(Product.current_price.is_(None))

        if category:
            q = q.filter(Product.keyword == category)

        total = q.count()

        sort_col = getattr(Product, sort_by, Product.created_at)
        sort_fn = desc if order == "desc" else asc
        q = q.order_by(sort_fn(sort_col))

        products = q.offset((page - 1) * per_page).limit(per_page).all()
        return products, total

    def get_filter_options(self) -> dict:
        """获取过滤选项和计数"""
        from sqlalchemy import func

        # 分类计数
        type_counts = (
            self.db.query(Product.card_type, func.count(Product.asin))
            .group_by(Product.card_type)
            .all()
        )
        # 关键词/品类计数
        keyword_counts = (
            self.db.query(Product.keyword, func.count(Product.asin))
            .filter(Product.keyword.isnot(None))
            .group_by(Product.keyword)
            .all()
        )
        # 价格状态计数
        has_price = (
            self.db.query(func.count(Product.asin))
            .filter(Product.current_price.isnot(None))
            .scalar()
            or 0
        )
        total = self.db.query(func.count(Product.asin)).scalar() or 0

        return {
            "card_types": {t: c for t, c in type_counts if t},
            "categories": {k: c for k, c in keyword_counts},
            "has_price": has_price,
            "no_price": total - has_price,
            "total": total,
        }

    def get_price_history(self, asin: str, limit: int = 30) -> list[PriceHistory]:
        """获取商品价格历史（最近 N 条）"""
        return (
            self.db.query(PriceHistory)
            .filter(PriceHistory.asin == asin)
            .order_by(asc(PriceHistory.recorded_at))
            .limit(limit)
            .all()
        )

    def get_price_drops(self, min_pct: float = 5.0) -> list[dict]:
        """获取降价商品列表（对比最新两次价格）"""
        drops = []
        products = self.db.query(Product).filter(Product.current_price.isnot(None)).all()

        for p in products:
            history = (
                self.db.query(PriceHistory)
                .filter(PriceHistory.asin == p.asin)
                .order_by(desc(PriceHistory.recorded_at))
                .limit(2)
                .all()
            )
            if len(history) < 2:
                continue

            latest, previous = history[0], history[1]
            if latest.price < previous.price:
                drop_pct = round((previous.price - latest.price) / previous.price * 100, 1)
                if drop_pct >= min_pct:
                    drops.append({
                        "asin": p.asin,
                        "title": p.title,
                        "old_price": previous.price,
                        "new_price": latest.price,
                        "drop_pct": drop_pct,
                        "image_url": p.image_url,
                    })

        drops.sort(key=lambda x: x["drop_pct"], reverse=True)
        return drops

    def delete_empty_products(self) -> int:
        """删除标题为空的垃圾商品数据，返回删除数量"""
        from app.storage.models import Product

        result = self.db.query(Product).filter(Product.title.is_(None)).delete(synchronize_session=False)
        self.db.commit()
        if result:
            logger.info(f"已清理 {result} 个空商品")
        return result

    def get_last_price(self, asin: str) -> float | None:
        """获取最近一次记录的价格"""
        last = (
            self.db.query(PriceHistory)
            .filter(PriceHistory.asin == asin)
            .order_by(desc(PriceHistory.recorded_at))
            .first()
        )
        return last.price if last else None

    def get_stats(self) -> dict:
        """获取仪表盘统计数据"""
        total = self.db.query(func.count(Product.asin)).scalar() or 0
        with_price = self.db.query(func.count(Product.asin)).filter(Product.current_price.isnot(None)).scalar() or 0
        avg_price = self.db.query(func.avg(Product.current_price)).filter(Product.current_price.isnot(None)).scalar()
        total_reviews = self.db.query(func.sum(Product.review_count)).filter(Product.review_count.isnot(None)).scalar() or 0
        drops = len(self.get_price_drops())

        return {
            "total_products": total,
            "products_with_price": with_price,
            "avg_price": round(float(avg_price), 2) if avg_price else None,
            "total_reviews": int(total_reviews),
            "price_drops": drops,
        }

    def get_all_asins(self) -> list[str]:
        """获取所有 ASIN 列表"""
        return [row[0] for row in self.db.query(Product.asin).all()]

    def get_asins_without_details(self) -> list[str]:
        """获取尚未采集详情页的 ASIN"""
        return [
            row[0]
            for row in self.db.query(Product.asin).filter(Product.detail_fetched == False).all()  # noqa: E712
        ]
