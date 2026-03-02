"""
bot/appeals.py
Read-only хелперы для работы с обращениями из registry/appeals/.
Запись — только через скрипты (appeals/add.sh, update.sh, reply.sh).
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_TRIAL_USERNAME = "trial"


def get_appeal(store_path: str, appeal_id: str) -> dict | None:
    path = Path(store_path) / "appeals" / f"{appeal_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read appeal %s: %s", appeal_id, e)
        return None


def list_appeals(
    store_path: str,
    *,
    status: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    appeals_dir = Path(store_path) / "appeals"
    if not appeals_dir.is_dir():
        return []

    result = []
    for file in appeals_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read %s: %s", file, e)
            continue

        if status is not None and data.get("status") != status:
            continue
        if user_id is not None and str(data.get("user_id", "")) != str(user_id):
            continue

        result.append(data)

    result.sort(key=lambda a: a.get("created", ""), reverse=True)
    return result


def list_users_for_broadcast(store_path: str) -> list[dict]:
    """Пользователи для рассылки: active + inactive, без trial и archived."""
    users_dir = Path(store_path) / "users"
    if not users_dir.is_dir():
        return []

    result = []
    for file in users_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read %s: %s", file, e)
            continue

        if data.get("status") == "archived":
            continue
        if data.get("username") == _TRIAL_USERNAME:
            continue
        if not data.get("telegram_id"):
            continue

        result.append(data)

    result.sort(key=lambda u: u.get("id", 0))
    return result
