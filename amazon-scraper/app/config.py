"""应用配置系统 — 基于 pydantic-settings，支持 YAML 文件 + 环境变量覆盖"""

from pathlib import Path
from typing import Optional

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


def _yaml_config_source(settings: BaseSettings) -> dict:
    """从 config.yaml 加载配置"""
    config_file = Path("config.yaml")
    if not config_file.exists():
        return {}
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AMAZON_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # ========== 数据库 ==========
    database_url: str = "sqlite:///data/amazon.db"

    # ========== 爬虫 ==========
    keywords: list[str] = [ "mouse", "keyboard"]
    max_list_pages: int = 5
    max_detail_asins: Optional[int] = None  # None = 全部采集
    request_delay_min: float = 2.0
    request_delay_max: float = 4.0
    detail_concurrency: int = 6
    page_timeout: int = 60  # 秒

    # ========== curl_cffi 模拟浏览器 ==========
    impersonate_target: str = "chrome120"

    # ========== 代理 ==========
    proxy_enabled: bool = False
    proxy_url: Optional[str] = None

    # ========== 通知 ==========
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # ========== 调度 ==========
    schedule_crawl_hour: int = 9
    schedule_monitor_interval: int = 6  # 小时

    # ========== Web ==========
    web_host: str = "0.0.0.0"
    web_port: int = 8000

    # ========== 路径 ==========
    data_dir: str = "data"
    log_dir: str = "logs"

    @property
    def request_delay(self) -> tuple[float, float]:
        return (self.request_delay_min, self.request_delay_max)

    @classmethod
    def from_yaml(cls) -> "Settings":
        """从 config.yaml 加载并返回 Settings 实例"""
        config_data = _yaml_config_source(cls)
        return cls(**config_data)


# 全局单例
settings = Settings.from_yaml()
