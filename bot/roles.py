import json
import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class Role(str, Enum):
    GUEST = "guest"
    USER = "user"
    ADMIN = "admin"


class GuestState(str, Enum):
    NO_RECORD = "no_record"   # нет записи в реестре
    PENDING   = "pending"     # inactive + core_nodes=[] (ожидает одобрения)
    BLOCKED   = "blocked"     # inactive + core_nodes не пустой (заблокирован)
    ARCHIVED  = "archived"    # archived (постоянный бан)


def resolve_guest_state(registry_user: dict | None) -> GuestState:
    if registry_user is None:
        return GuestState.NO_RECORD
    status = registry_user.get("status")
    if status == "archived":
        return GuestState.ARCHIVED
    if status == "inactive":
        if not registry_user.get("core_nodes"):
            return GuestState.PENDING
        return GuestState.BLOCKED
    return GuestState.NO_RECORD


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
                    if data.get("telegram_id") == telegram_id and data.get("status") == "active":
                        return Role.USER
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read %s: %s", file, e)

    return Role.GUEST
