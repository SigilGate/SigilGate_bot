from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from bot.roles import GuestState, Role, resolve_guest_state

router = Router()


COMMANDS_USER = (
    "Доступные команды:\n"
    "/devices — список устройств"
)

COMMANDS_ADMIN = (
    "Команды администратора:\n"
    "/users — управление пользователями\n"
    "\n"
    "Команды пользователя:\n"
    "/devices — список устройств"
)

GUEST_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🚀 Пробный доступ (без регистрации)")],
        [KeyboardButton(text="📝 Зарегистрироваться")],
    ],
    resize_keyboard=True,
)

GUEST_MESSAGES = {
    GuestState.NO_RECORD: "Добро пожаловать в Sigil Gate!",
    GuestState.PENDING: (
        "Ваша заявка принята и рассматривается администратором.\n"
        "Обратитесь к администратору для получения доступа."
    ),
    GuestState.BLOCKED: (
        "Ваш аккаунт неактивен.\n"
        "Обратитесь к администратору."
    ),
    GuestState.ARCHIVED: (
        "Ваш аккаунт заблокирован.\n"
        "Обратитесь к администратору."
    ),
}


@router.message(CommandStart())
async def cmd_start(message: Message, role: Role, registry_user: dict | None) -> None:
    if role == Role.ADMIN:
        await message.answer(f"Sigil Gate — панель администратора.\n\n{COMMANDS_ADMIN}")
    elif role == Role.USER:
        name = registry_user.get("username", "") if registry_user else ""
        await message.answer(f"Добро пожаловать, {name}!\n\n{COMMANDS_USER}")
    else:
        state = resolve_guest_state(registry_user)
        if state == GuestState.NO_RECORD:
            await message.answer(GUEST_MESSAGES[state], reply_markup=GUEST_KEYBOARD)
        else:
            await message.answer(GUEST_MESSAGES[state])
