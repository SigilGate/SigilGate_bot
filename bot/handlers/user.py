from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.roles import Role

router = Router()


@router.message(Command("devices"))
async def cmd_devices(message: Message, role: Role) -> None:
    if role in (Role.USER, Role.ADMIN):
        await message.answer("Здесь будет список ваших устройств.")
    else:
        await message.answer("Доступ ограничен.")


@router.message(Command("add_device"))
async def cmd_add_device(message: Message, role: Role) -> None:
    if role in (Role.USER, Role.ADMIN):
        await message.answer("Здесь будет добавление устройства.")
    else:
        await message.answer("Доступ ограничен.")


@router.message(Command("remove_device"))
async def cmd_remove_device(message: Message, role: Role) -> None:
    if role in (Role.USER, Role.ADMIN):
        await message.answer("Здесь будет удаление устройства.")
    else:
        await message.answer("Доступ ограничен.")
