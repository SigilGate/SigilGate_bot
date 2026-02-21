import os
import sys
import logging

logger = logging.getLogger(__name__)

def load_config() -> dict:
    token = os.environ.get("SIGILGATE_BOT_TOKEN", "")
    if not token:
        logger.error("SIGILGATE_BOT_TOKEN is not set")
        sys.exit(1)

    store_path = os.environ.get("SIGIL_STORE_PATH", "")
    if not store_path:
        logger.warning("SIGIL_STORE_PATH is not set, role detection will not work")

    admin_ids_raw = os.environ.get("SIGILGATE_ADMIN_IDS", "")
    admin_ids: set[int] = set()
    for part in admin_ids_raw.split(","):
        part = part.strip()
        if part.isdigit():
            admin_ids.add(int(part))

    scripts_path = os.environ.get("SIGIL_SCRIPTS_PATH", "")
    if not scripts_path:
        logger.warning("SIGIL_SCRIPTS_PATH is not set, script execution will not work")

    verbose = os.environ.get("SIGILGATE_VERBOSE", "").lower() in ("1", "true", "yes")

    return {
        "token": token,
        "store_path": store_path,
        "admin_ids": admin_ids,
        "scripts_path": scripts_path,
        "verbose": verbose,
    }
