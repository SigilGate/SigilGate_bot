import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from bot.roles import Role, resolve_role

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
            role = resolve_role(user.id, self.store_path, self.admin_ids)
            data["role"] = role
            logger.debug("User %s (id=%d) -> role=%s", user.full_name, user.id, role.value)
        else:
            data["role"] = Role.GUEST

        return await handler(event, data)
