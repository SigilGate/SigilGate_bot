from aiogram import F, Router
from aiogram.types import Message

from bot.roles import Role

router = Router()


@router.message(F.text)
async def guest_fallback(message: Message, role: Role) -> None:
    if role == Role.GUEST:
        await message.answer(
            "Доступ ограничен.\n"
            "Для получения доступа обратитесь к администратору."
        )
