from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from bot.roles import GuestState, Role, resolve_guest_state

router = Router()

GUEST_FALLBACK_MESSAGES = {
    GuestState.NO_RECORD: (
        "Доступ ограничен.\n"
        "Используйте /reg для подачи заявки на подключение."
    ),
    GuestState.PENDING: (
        "Ваша заявка рассматривается администратором.\n"
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


@router.message(F.text, StateFilter(None))
async def guest_fallback(message: Message, role: Role, registry_user: dict | None) -> None:
    if role == Role.GUEST:
        state = resolve_guest_state(registry_user)
        await message.answer(GUEST_FALLBACK_MESSAGES[state])
