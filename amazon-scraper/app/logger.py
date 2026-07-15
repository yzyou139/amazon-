"""日志系统 — 基于 loguru，控制台 + 文件双输出，自动轮转"""

import sys
from pathlib import Path

from loguru import logger

from app.config import settings

# 移除默认 handler
logger.remove()

# 控制台输出 — 彩色格式
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True,
)

# 确保日志目录存在
log_dir = Path(settings.log_dir)
log_dir.mkdir(parents=True, exist_ok=True)

# 全量日志文件 — 保留 7 天
logger.add(
    log_dir / "app_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    level="DEBUG",
    rotation="00:00",  # 每天午夜轮转
    retention="7 days",
    encoding="utf-8",
    enqueue=True,  # 多进程安全
)

# 错误日志单独文件
logger.add(
    log_dir / "error_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    level="ERROR",
    rotation="00:00",
    retention="30 days",
    encoding="utf-8",
    enqueue=True,
)

__all__ = ["logger"]
