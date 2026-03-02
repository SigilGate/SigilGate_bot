"""
bot/handlers/announce.py
Команда /send — рассылка сообщений от администратора через бот.

Цели:
  - channel   — канал (SIGILGATE_CHANNEL_ID)
  - broadcast — всем пользователям (active + inactive, без trial/archived)
  - user      — конкретному пользователю
  - all       — канал + все пользователи

Администратор остается скрыт от получателей — все сообщения идут от бота.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter, or_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.appeals import list_users_for_broadcast
from bot.roles import Role

logger = logging.getLogger(__name__)

router = Router()

_MAX_SUBJECT_LEN = 40


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------

class SendState(StatesGroup):
    selecting_target = State()
    selecting_user   = State()
    entering_text    = State()
    confirming       = State()


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _kb_targets() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 На канал",         callback_data="send:t:channel")],
        [InlineKeyboardButton(text="📣 Рассылка",         callback_data="send:t:broadcast")],
        [InlineKeyboardButton(text="👤 Пользователь",     callback_data="send:t:user")],
        [InlineKeyboardButton(text="🌐 Всем",             callback_data="send:t:all")],
        [InlineKeyboardButton(text="✗ Отмена",           callback_data="send:cancel")],
    ])


def _kb_users(users: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        label = u["username"]
        status = u.get("status", "")
        if status == "inactive":
            label = f"⏸ {label}"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"send:u:{u['telegram_id']}:{u['username'][:20]}",
        )])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="send:back_to_targets")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✓ Отправить", callback_data="send:confirm"),
        InlineKeyboardButton(text="✗ Отмена",    callback_data="send:cancel"),
    ]])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _target_label(target: str, user_count: int = 0) -> str:
    if target == "channel":
        return "На канал"
    if target == "broadcast":
        return f"Рассылка ({user_count} польз.)"
    if target == "all":
        return f"Всем: канал + {user_count} польз."
    if target.startswith("user:"):
        _, tg_id, username = target.split(":", 2)
        return f"Пользователю @{username}"
    return target


async def _do_send(
    bot: Bot,
    target: str,
    text: str,
    store_path: str,
    channel_id: str,
) -> tuple[int, int]:
    """Выполнить рассылку. Возвращает (sent, failed)."""
    sent = failed = 0

    async def _send_to(chat_id: int | str) -> bool:
        nonlocal sent, failed
        try:
            await bot.send_message(chat_id, text)
            sent += 1
            return True
        except Exception as e:
            logger.warning("Failed to send message to %s: %s", chat_id, e)
            failed += 1
            return False

    if target in ("channel", "all"):
        if channel_id:
            await _send_to(channel_id)
        else:
            logger.warning("SIGILGATE_CHANNEL_ID not set, skipping channel")

    if target in ("broadcast", "all"):
        users = list_users_for_broadcast(store_path)
        for user in users:
            await _send_to(user["telegram_id"])

    if target.startswith("user:"):
        _, tg_id, _ = target.split(":", 2)
        await _send_to(int(tg_id))

    return sent, failed


# ---------------------------------------------------------------------------
# /send
# ---------------------------------------------------------------------------

@router.message(or_f(Command("send"), F.text == "📨 Отправить сообщение"))
async def cmd_send(message: Message, role: Role, state: FSMContext) -> None:
    if role != Role.ADMIN:
        await message.answer("Доступ ограничен.")
        return

    await state.set_state(SendState.selecting_target)
    await message.answer("Выберите получателей:", reply_markup=_kb_targets())


# ---------------------------------------------------------------------------
# Выбор цели
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(SendState.selecting_target), F.data.startswith("send:t:"))
async def cb_select_target(
    callback: CallbackQuery,
    role: Role,
    state: FSMContext,
    store_path: str,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    target = callback.data.split(":")[2]  # channel | broadcast | user | all

    if target == "user":
        users = list_users_for_broadcast(store_path)
        if not users:
            await callback.answer("Нет доступных пользователей.", show_alert=True)
            return
        await state.set_state(SendState.selecting_user)
        await callback.message.edit_text("Выберите пользователя:", reply_markup=_kb_users(users))
    else:
        await state.update_data(target=target)
        await state.set_state(SendState.entering_text)
        await callback.message.edit_text("Введите текст сообщения:")

    await callback.answer()


# ---------------------------------------------------------------------------
# Выбор конкретного пользователя
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(SendState.selecting_user), F.data.startswith("send:u:"))
async def cb_select_user(
    callback: CallbackQuery,
    role: Role,
    state: FSMContext,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # send:u:<telegram_id>:<username>
    parts = callback.data.split(":", 3)
    tg_id    = parts[2]
    username = parts[3] if len(parts) > 3 else tg_id

    await state.update_data(target=f"user:{tg_id}:{username}")
    await state.set_state(SendState.entering_text)
    await callback.message.edit_text(
        f"Получатель: {username}\n\nВведите текст сообщения:"
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Назад к выбору цели
# ---------------------------------------------------------------------------

@router.callback_query(
    StateFilter(SendState.selecting_user, SendState.selecting_target),
    F.data == "send:back_to_targets",
)
async def cb_back_to_targets(
    callback: CallbackQuery,
    role: Role,
    state: FSMContext,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    await state.set_state(SendState.selecting_target)
    await callback.message.edit_text("Выберите получателей:", reply_markup=_kb_targets())
    await callback.answer()


# ---------------------------------------------------------------------------
# Ввод текста
# ---------------------------------------------------------------------------

@router.message(StateFilter(SendState.entering_text))
async def on_text_entered(
    message: Message,
    role: Role,
    state: FSMContext,
    store_path: str,
) -> None:
    if role != Role.ADMIN:
        return

    text = message.text or ""
    if not text.strip():
        await message.answer("Сообщение не может быть пустым. Введите текст:")
        return

    data = await state.get_data()
    target = data.get("target", "")

    await state.update_data(text=text)
    await state.set_state(SendState.confirming)

    # Для broadcast/all — посчитать получателей
    user_count = 0
    if target in ("broadcast", "all"):
        user_count = len(list_users_for_broadcast(store_path))

    label = _target_label(target, user_count)
    subject = text[:_MAX_SUBJECT_LEN] + ("…" if len(text) > _MAX_SUBJECT_LEN else "")

    preview = (
        f"<b>Предпросмотр</b>\n"
        f"Получатели: {label}\n"
        f"───────────────────\n"
        f"{subject}\n"
        f"───────────────────\n"
        f"Отправить сообщение?"
    )
    await message.answer(preview, parse_mode="HTML", reply_markup=_kb_confirm())


# ---------------------------------------------------------------------------
# Подтверждение и отправка
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(SendState.confirming), F.data == "send:confirm")
async def cb_confirm(
    callback: CallbackQuery,
    role: Role,
    state: FSMContext,
    bot: Bot,
    store_path: str,
    channel_id: str,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    data = await state.get_data()
    target = data.get("target", "")
    text   = data.get("text", "")

    await state.clear()
    await callback.message.edit_text("Отправляю...")

    sent, failed = await _do_send(bot, target, text, store_path, channel_id)

    if failed == 0:
        result = f"Отправлено: {sent}"
    else:
        result = f"Отправлено: {sent}, ошибок: {failed}"

    await callback.message.edit_text(f"Готово. {result}")
    await callback.answer()


# ---------------------------------------------------------------------------
# Отмена (из любого состояния)
# ---------------------------------------------------------------------------

@router.callback_query(
    StateFilter(SendState.selecting_target, SendState.selecting_user,
                SendState.entering_text, SendState.confirming),
    F.data == "send:cancel",
)
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Отменено.")
    await callback.answer()
