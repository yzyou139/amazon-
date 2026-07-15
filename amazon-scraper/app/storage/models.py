"""SQLAlchemy ORM 模型 — Product + PriceHistory"""

from datetime import datetime, timezone

from sqlalchemy import Float, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    # 主键
    asin: Mapped[str] = mapped_column(String(20), primary_key=True, comment="Amazon Standard Identification Number")

    # === 列表页字段 ===
    card_type: Mapped[str | None] = mapped_column(String(50), default=None, comment="卡片类型: 主搜索结果/广告位/轮播推荐")
    keyword: Mapped[str | None] = mapped_column(String(100), default=None, comment="采集时使用的搜索关键词（如 mouse/手柄）")
    title: Mapped[str | None] = mapped_column(Text, default=None, comment="商品标题")
    current_price: Mapped[float | None] = mapped_column(Float, default=None, comment="当前售价(数值)")
    current_price_raw: Mapped[str | None] = mapped_column(String(50), default=None, comment="当前售价(原始文本，含货币符号)")
    list_price: Mapped[float | None] = mapped_column(Float, default=None, comment="划线原价(数值)")
    list_price_raw: Mapped[str | None] = mapped_column(String(50), default=None, comment="划线原价(原始文本)")
    rating: Mapped[float | None] = mapped_column(Float, default=None, comment="星级评分 1.0-5.0")
    review_count: Mapped[int | None] = mapped_column(Integer, default=None, comment="评论总数")
    monthly_sales: Mapped[str | None] = mapped_column(String(200), default=None, comment="近月销量文字")
    delivery_info: Mapped[str | None] = mapped_column(String(500), default=None, comment="配送信息")
    image_url: Mapped[str | None] = mapped_column(String(1000), default=None, comment="商品主图URL")

    # === 详情页字段 ===
    brand: Mapped[str | None] = mapped_column(String(200), default=None, comment="品牌")
    bullet_points: Mapped[str | None] = mapped_column(Text, default=None, comment="五点描述 JSON")
    description: Mapped[str | None] = mapped_column(Text, default=None, comment="商品描述")
    specifications: Mapped[str | None] = mapped_column(Text, default=None, comment="技术规格 JSON 对象")
    images: Mapped[str | None] = mapped_column(Text, default=None, comment="商品图片 JSON 数组")
    in_stock: Mapped[str | None] = mapped_column(String(100), default=None, comment="库存状态")

    # === 元数据 ===
    detail_fetched: Mapped[bool] = mapped_column(default=False, comment="是否已采集详情页")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), comment="首次采集时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="最后更新时间",
    )

    # 关联
    price_history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Product(asin={self.asin}, title={self.title[:30] if self.title else 'N/A'}...)>"


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asin: Mapped[str] = mapped_column(String(20), ForeignKey("products.asin", ondelete="CASCADE"), comment="关联 ASIN")
    price: Mapped[float] = mapped_column(Float, comment="价格(数值)")
    price_raw: Mapped[str | None] = mapped_column(String(50), default=None, comment="价格(原始文本)")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), comment="记录时间"
    )

    # 反向关联
    product: Mapped["Product"] = relationship(back_populates="price_history")

    def __repr__(self) -> str:
        return f"<PriceHistory(asin={self.asin}, price={self.price}, at={self.recorded_at})>"
