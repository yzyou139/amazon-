"""价格监控 — 检测价格变化，记录历史，识别降价商品"""

from app.logger import logger
from app.storage.repository import ProductRepository


def record_price_snapshots(repo: ProductRepository | None = None):
    """
    为所有有价格的商品记录当前价格快照。

    只有价格与最近一次记录不同时才会创建新记录。
    """
    if repo is None:
        with ProductRepository() as repo:
            _record_snapshots(repo)
    else:
        _record_snapshots(repo)


def _record_snapshots(repo: ProductRepository):
    from app.storage.models import Product

    products = repo.db.query(Product).filter(Product.current_price.isnot(None)).all()

    recorded = 0
    skipped = 0
    for p in products:
        result = repo.record_price(p.asin, p.current_price, p.current_price_raw)
        if result:
            recorded += 1
        else:
            skipped += 1

    logger.info(f"价格快照完成: 记录 {recorded} 条新价格, 跳过 {skipped} 条（价格未变）")


def check_price_drops(min_drop_pct: float = 5.0) -> list[dict]:
    """
    检查降价商品。

    Args:
        min_drop_pct: 最小降价百分比阈值

    Returns:
        降价商品列表 [{"asin", "title", "old_price", "new_price", "drop_pct", "image_url"}, ...]
    """
    with ProductRepository() as repo:
        return repo.get_price_drops(min_pct=min_drop_pct)


def run_price_monitor(min_drop_pct: float = 5.0) -> list[dict]:
    """
    执行一轮完整价格监控：
    1. 记录当前价格快照
    2. 检查降价商品
    3. 返回降价列表

    Args:
        min_drop_pct: 最小降价百分比阈值

    Returns:
        降价商品列表
    """
    logger.info("===== 开始价格监控 =====")

    with ProductRepository() as repo:
        # 步骤1: 记录快照
        _record_snapshots(repo)

        # 步骤2: 检查降价
        drops = repo.get_price_drops(min_pct=min_drop_pct)

    # 输出结果
    if drops:
        logger.info(f"发现 {len(drops)} 个降价商品:")
        for d in drops:
            logger.info(
                f"  📉 {d['title'][:40]}... "
                f"${d['old_price']:.2f} → ${d['new_price']:.2f} "
                f"(-{d['drop_pct']}%)"
            )
    else:
        logger.info("未发现降价商品")

    logger.info("===== 价格监控完成 =====")
    return drops
