import io
import logging

import qrcode
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)


def make_qr_photo(link: str) -> BufferedInputFile | None:
    """Генерирует QR-код для VLESS-ссылки. Возвращает None при ошибке."""
    try:
        img = qrcode.make(link)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return BufferedInputFile(buf.read(), filename="qr.png")
    except Exception:
        logger.exception("Failed to generate QR code")
        return None
