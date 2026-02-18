import json
import logging
import os
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class Role(str, Enum):
    GUEST = "guest"
    USER = "user"
    ADMIN = "admin"


def find_user_by_telegram_id(telegram_id: int, store_path: str) -> dict | None:
    if not store_path:
        return None
    users_dir = Path(store_path) / "users"
    if not users_dir.is_dir():
        return None
    for file in users_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text())
            if data.get("telegram_id") == telegram_id:
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read %s: %s", file, e)
    return None


def resolve_role(telegram_id: int, store_path: str, admin_ids: set[int]) -> Role:
    if telegram_id in admin_ids:
        return Role.ADMIN

    if store_path:
        users_dir = Path(store_path) / "users"
        if users_dir.is_dir():
            for file in users_dir.glob("*.json"):
                try:
                    data = json.loads(file.read_text())
                    if data.get("telegram_id") == telegram_id:
                        return Role.USER
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read %s: %s", file, e)

    return Role.GUEST
