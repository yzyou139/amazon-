"""通知推送 — 支持 Telegram Bot、控制台输出等渠道"""

import httpx

from app.config import settings
from app.logger import logger


class BaseNotifier:
    """通知基类"""

    def send_price_alert(self, product: dict) -> bool:
        raise NotImplementedError


class ConsoleNotifier(BaseNotifier):
    """控制台通知（默认）"""

    def send_price_alert(self, product: dict) -> bool:
        title = (product.get("title") or "Unknown")[:50]
        old_price = product.get("old_price", 0)
        new_price = product.get("new_price", 0)
        drop_pct = product.get("drop_pct", 0)

        msg = (
            f"\n{'=' * 50}\n"
            f"📉 降价提醒!\n"
            f"商品: {title}\n"
            f"原价: ${old_price:.2f}\n"
            f"现价: ${new_price:.2f}\n"
            f"降幅: {drop_pct}%\n"
            f"ASIN: {product.get('asin', 'N/A')}\n"
            f"{'=' * 50}"
        )
        print(msg)
        return True


class TelegramNotifier(BaseNotifier):
    """Telegram Bot 通知"""

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        self.bot_token = bot_token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self._api_base = f"https://api.telegram.org/bot{self.bot_token}"

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_price_alert(self, product: dict) -> bool:
        if not self.is_configured:
            logger.warning("Telegram 未配置，跳过推送")
            return False

        title = (product.get("title") or "Unknown")[:80]
        asin = product.get("asin", "N/A")
        old_price = product.get("old_price", 0)
        new_price = product.get("new_price", 0)
        drop_pct = product.get("drop_pct", 0)

        message = (
            f"📉 <b>降价提醒!</b>\n\n"
            f"<b>商品:</b> {title}\n"
            f"<b>原价:</b> ${old_price:.2f}\n"
            f"<b>现价:</b> ${new_price:.2f}\n"
            f"<b>降幅:</b> {drop_pct}%\n"
            f'\n<a href="https://www.amazon.com/dp/{asin}">🔗 查看商品</a>'
        )

        try:
            resp = httpx.post(
                f"{self._api_base}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info(f"Telegram 推送成功: {asin}")
                return True
            else:
                logger.error(f"Telegram 推送失败: {resp.status_code} — {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram 推送异常: {e}")
            return False


def get_notifier() -> BaseNotifier:
    """
    获取通知器实例。
    优先 Telegram（已配置时），否则回退到控制台输出。
    """
    telegram = TelegramNotifier()
    if telegram.is_configured:
        logger.info("使用 Telegram 通知")
        return telegram
    logger.info("使用控制台通知")
    return ConsoleNotifier()
