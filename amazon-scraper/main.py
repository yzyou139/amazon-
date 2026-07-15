#!/usr/bin/env python
"""Amazon Product Scraper & Price Monitor — CLI 入口

Usage:
    python main.py crawl -k "gaming mouse" -p 3    # 采集数据
    python main.py crawl --all                       # 采集所有配置关键词
    python main.py monitor                           # 运行价格监控
    python main.py web                               # 启动 Web Dashboard
    python main.py schedule                          # 启动定时调度
"""

import asyncio
import json
import sys
from pathlib import Path

import click

from app.config import settings
from app.logger import logger
from app.storage.database import init_db


@click.group()
@click.version_option(version="2.0.0")
def cli():
    """Amazon Product Scraper & Price Monitor"""


# ============================================================
# crawl — 采集商品数据
# ============================================================
@cli.command()
@click.option("--keyword", "-k", default=None, help="搜索关键词（多个用逗号分隔）")
@click.option("--pages", "-p", default=None, type=int, help="每个关键词采集页数")
@click.option("--concurrency", "-c", default=None, type=int, help="详情页并发数")
@click.option("--all", "all_keywords", is_flag=True, help="采集所有配置中的关键词")
@click.option("--force-details", is_flag=True, help="强制重新采集所有详情页（包括已采集的）")
def crawl(keyword, pages, concurrency, all_keywords, force_details):
    """
    采集亚马逊商品数据。

    执行两步操作：
    1. 列表页采集 → 解析 → 入库
    2. 详情页采集 → 解析 → 补充入库
    """
    init_db()
    logger.info("===== 开始数据采集 =====")

    # 确定关键词
    if all_keywords or not keyword:
        keywords = settings.keywords
    else:
        keywords = [k.strip() for k in keyword.split(",")]

    max_pages = pages or settings.max_list_pages
    detail_concurrency = concurrency or settings.detail_concurrency

    # ===== Step 1: 列表页采集 =====
    from app.crawler.list_crawler import crawl_all_keywords, crawl_list_pages_for_keyword
    from app.parser.list_parser import parse_raw_data
    from app.storage.repository import ProductRepository

    # 临时覆盖配置
    original_keywords = settings.keywords
    original_pages = settings.max_list_pages
    settings.keywords = keywords
    settings.max_list_pages = max_pages

    try:
        all_raw = crawl_all_keywords()
    finally:
        settings.keywords = original_keywords
        settings.max_list_pages = original_pages

    # 解析所有数据
    all_products = []
    for kw, raw_data in all_raw.items():
        if raw_data:
            products = parse_raw_data(raw_data)
            # 给每个商品打上搜索关键词标签
            for p in products:
                p["keyword"] = kw
            logger.info(f"关键词 '{kw}': 解析出 {len(products)} 个商品")
            all_products.extend(products)

    # 去重后入库
    seen = set()
    unique_products = []
    for p in all_products:
        if p["asin"] not in seen:
            unique_products.append(p)
            seen.add(p["asin"])

    with ProductRepository() as repo:
        repo.bulk_upsert_products(unique_products)

    logger.info(f"列表页完成: {len(unique_products)} 个唯一商品入库")

    # ===== Step 2: 详情页采集 =====
    from app.crawler.detail_crawler import crawl_detail_pages
    from app.parser.detail_parser import parse_detail_page

    with ProductRepository() as repo:
        if force_details:
            from app.storage.models import Product
            pending_asins = [p.asin for p in repo.db.query(Product).all()]
            logger.info(f"强制重新采集所有详情页: {len(pending_asins)} 个 ASIN")
        else:
            pending_asins = repo.get_asins_without_details()
        max_detail = settings.max_detail_asins
        if max_detail:
            pending_asins = pending_asins[:max_detail]

    if pending_asins:
        logger.info(f"开始详情页采集: {len(pending_asins)} 个 ASIN")
        results = asyncio.run(crawl_detail_pages(pending_asins, detail_concurrency))

        with ProductRepository() as repo:
            for asin, html_text, error in results:
                if html_text:
                    detail = parse_detail_page(asin, html_text)
                    repo.upsert_product(detail)
                    # ⚠️ 不在这里记录价格快照，由 monitor 命令统一管理
                    # 避免被拦截的页面返回错误价格污染价格历史
        logger.info("详情页采集完成")
    else:
        logger.info("无待采集的详情页")

    logger.info("===== 数据采集完成 =====")


# ============================================================
# monitor — 价格监控
# ============================================================
@cli.command()
@click.option("--min-pct", default=5.0, type=float, help="最小降价百分比阈值")
@click.option("--notify", is_flag=True, help="发送通知（Telegram 或控制台）")
def monitor(min_pct, notify):
    """运行价格监控，检测降价商品"""
    init_db()

    from app.monitor.price_checker import run_price_monitor

    drops = run_price_monitor(min_drop_pct=min_pct)

    if drops and notify:
        from app.monitor.notifier import get_notifier

        notifier = get_notifier()
        for drop in drops:
            notifier.send_price_alert(drop)


# ============================================================
# cleanup — 清理空商品
# ============================================================
@cli.command()
def cleanup():
    """清理数据库中标题为空的垃圾商品数据"""
    init_db()

    from app.storage.repository import ProductRepository

    with ProductRepository() as repo:
        count = repo.delete_empty_products()
        if count:
            logger.info(f"✅ 已清理 {count} 个空商品")
        else:
            logger.info("✅ 没有需要清理的空商品")


# ============================================================
# web — Web Dashboard
# ============================================================
@cli.command()
@click.option("--host", default=None, help="监听地址")
@click.option("--port", default=None, type=int, help="监听端口")
def web(host, port):
    """启动 Web Dashboard"""
    import uvicorn

    init_db()

    bind_host = host or settings.web_host
    bind_port = port or settings.web_port

    logger.info(f"Web Dashboard 启动: http://{bind_host}:{bind_port}")
    uvicorn.run(
        "app.web.app:app",
        host=bind_host,
        port=bind_port,
        log_level="info",
    )


# ============================================================
# schedule — 定时调度
# ============================================================
@cli.command()
def schedule():
    """启动定时调度（每日采集 + 定期价格监控）"""
    init_db()

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = BackgroundScheduler()

    # 每日定时采集
    crawl_hour = settings.schedule_crawl_hour

    def scheduled_crawl():
        logger.info("⏰ 定时采集触发")
        # 通过 click 调用 crawl 命令
        import subprocess

        subprocess.run([sys.executable, "main.py", "crawl", "--all"])

    scheduler.add_job(
        scheduled_crawl,
        trigger=CronTrigger(hour=crawl_hour, minute=7),
        id="daily_crawl",
        name="每日自动采集",
    )

    # 定期价格检查
    monitor_interval = settings.schedule_monitor_interval

    def scheduled_monitor():
        logger.info("⏰ 定时价格检查触发")
        from app.monitor.price_checker import run_price_monitor
        from app.monitor.notifier import get_notifier

        drops = run_price_monitor()
        if drops:
            notifier = get_notifier()
            for drop in drops:
                notifier.send_price_alert(drop)

    scheduler.add_job(
        scheduled_monitor,
        trigger=IntervalTrigger(hours=monitor_interval),
        id="price_monitor",
        name="定期价格检查",
    )

    scheduler.start()
    logger.info(
        f"定时调度已启动: "
        f"每日 {crawl_hour:02d}:07 采集, "
        f"每 {monitor_interval} 小时价格检查"
    )
    logger.info("按 Ctrl+C 停止")

    try:
        import time

        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("调度器已停止")
        scheduler.shutdown()


if __name__ == "__main__":
    cli()
