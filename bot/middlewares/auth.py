import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from bot.roles import Role, find_user_by_telegram_id, resolve_role

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    def __init__(self, store_path: str, admin_ids: set[int]) -> None:
        self.store_path = store_path
        self.admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Update):
            if event.message and event.message.from_user:
                user = event.message.from_user
            elif event.callback_query and event.callback_query.from_user:
                user = event.callback_query.from_user

        if user:
            registry_user = await asyncio.to_thread(find_user_by_telegram_id, user.id, self.store_path)
            if user.id in self.admin_ids:
                role = Role.ADMIN
            elif registry_user is not None:
                role = Role.USER
            else:
                role = Role.GUEST
            data["role"] = role
            data["registry_user"] = registry_user
            logger.debug("User %s (id=%d) -> role=%s", user.full_name, user.id, role.value)
        else:
            data["role"] = Role.GUEST
            data["registry_user"] = None

        return await handler(event, data)
