from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.roles import Role

router = Router()


COMMANDS_GUEST = (
    "Доступные команды:\n"
    "/start — информация о боте\n"
    "/reg — подать заявку на подключение"
)

COMMANDS_USER = (
    "Доступные команды:\n"
    "/devices — список устройств\n"
    "/add_device — добавить устройство\n"
    "/remove_device — удалить устройство"
)

COMMANDS_ADMIN = (
    "Команды администратора:\n"
    "/users — управление пользователями\n"
    "/status — статус сети\n"
    "\n"
    "Команды пользователя:\n"
    "/devices — список устройств\n"
    "/add_device — добавить устройство\n"
    "/remove_device — удалить устройство"
)


@router.message(CommandStart())
async def cmd_start(message: Message, role: Role) -> None:
    greeting = f"Добро пожаловать в Sigil Gate Bot!\nВаша роль: {role.value}\n\n"

    if role == Role.ADMIN:
        await message.answer(greeting + COMMANDS_ADMIN)
    elif role == Role.USER:
        await message.answer(greeting + COMMANDS_USER)
    else:
        await message.answer(greeting + COMMANDS_GUEST)
