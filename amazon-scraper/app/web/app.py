"""FastAPI 应用 — Amazon Scraper Web Dashboard"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.web.routes import router

# 创建 FastAPI 应用
app = FastAPI(
    title="Amazon Price Monitor",
    description="亚马逊商品数据采集与价格监控系统",
    version="2.0.0",
)

# 注册路由
app.include_router(router)

# 静态文件（可选，用于自定义 CSS/JS）
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
