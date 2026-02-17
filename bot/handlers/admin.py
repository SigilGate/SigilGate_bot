from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.roles import Role

router = Router()


@router.message(Command("users"))
async def cmd_users(message: Message, role: Role) -> None:
    if role == Role.ADMIN:
        await message.answer("Здесь будет управление пользователями.")
    else:
        await message.answer("Доступ ограничен.")


@router.message(Command("status"))
async def cmd_status(message: Message, role: Role) -> None:
    if role == Role.ADMIN:
        await message.answer("Здесь будет статус сети.")
    else:
        await message.answer("Доступ ограничен.")
