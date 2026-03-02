from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from bot.roles import GuestState, Role, resolve_guest_state

router = Router()

# Тексты кнопок — используются также как фильтры в других хендлерах
BTN_DEVICES  = "📱 Устройства"
BTN_APPEALS  = "📋 Обращения"
BTN_SUPPORT  = "✍ Написать администратору"
BTN_USERS    = "👥 Пользователи"
BTN_SEND     = "📨 Отправить сообщение"

USER_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_DEVICES), KeyboardButton(text=BTN_APPEALS)],
        [KeyboardButton(text=BTN_SUPPORT)],
    ],
    resize_keyboard=True,
)

ADMIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_USERS), KeyboardButton(text=BTN_APPEALS)],
        [KeyboardButton(text=BTN_SEND)],
    ],
    resize_keyboard=True,
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
        await message.answer(
            "Sigil Gate — панель администратора.",
            reply_markup=ADMIN_KEYBOARD,
        )
    elif role == Role.USER:
        name = registry_user.get("username", "") if registry_user else ""
        await message.answer(
            f"Добро пожаловать, {name}!",
            reply_markup=USER_KEYBOARD,
        )
    else:
        state = resolve_guest_state(registry_user)
        if state == GuestState.NO_RECORD:
            await message.answer(GUEST_MESSAGES[state], reply_markup=GUEST_KEYBOARD)
        else:
            await message.answer(GUEST_MESSAGES[state])
