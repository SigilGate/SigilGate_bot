from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from bot.roles import Role

router = Router()


@router.message(F.text, StateFilter(None))
async def guest_fallback(message: Message, role: Role) -> None:
    if role == Role.GUEST:
        await message.answer(
            "Доступ ограничен.\n"
            "Используйте /reg для подачи заявки на подключение."
        )
