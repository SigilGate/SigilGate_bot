"""
bot/crypto.py
Утилиты шифрования и хеширования Telegram ID.

Переменные окружения:
  SIGIL_TELEGRAM_ENCRYPTION_KEY — Fernet-ключ (base64url, 44 символа)
  SIGIL_TELEGRAM_HASH_KEY       — HMAC-ключ (произвольная строка, рекомендуется 32+ символа)

Генерация ключей:
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  python3 -c "import secrets; print(secrets.token_hex(32))"
"""

import hmac
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    key = os.environ.get("SIGIL_TELEGRAM_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("SIGIL_TELEGRAM_ENCRYPTION_KEY не задан")
    return Fernet(key.encode())


def _hash_key() -> bytes:
    key = os.environ.get("SIGIL_TELEGRAM_HASH_KEY", "")
    if not key:
        raise RuntimeError("SIGIL_TELEGRAM_HASH_KEY не задан")
    return key.encode()


def hash_telegram_id(telegram_id: int) -> str:
    """HMAC-SHA256 хеш telegram_id. Возвращает hex-строку (64 символа)."""
    return hmac.new(_hash_key(), str(telegram_id).encode(), hashlib.sha256).hexdigest()


def encrypt_telegram_id(telegram_id: int) -> str:
    """Fernet-шифрование telegram_id. Возвращает строку токена."""
    return _fernet().encrypt(str(telegram_id).encode()).decode()


def decrypt_telegram_id(token: str) -> int:
    """Расшифровывает Fernet-токен и возвращает telegram_id как int."""
    try:
        return int(_fernet().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError) as e:
        raise ValueError(f"Не удалось расшифровать telegram_id: {e}") from e
