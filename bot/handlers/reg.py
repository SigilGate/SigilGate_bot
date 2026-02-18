import json
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import DEFAULT_STATE
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.roles import Role
from bot.runner import run_script

logger = logging.getLogger(__name__)

router = Router()


class RegStates(StatesGroup):
    waiting_username = State()
    waiting_email = State()
    confirm = State()


def _kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="reg:cancel")],
    ])


def _kb_email() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Пропустить", callback_data="reg:skip_email"),
            InlineKeyboardButton(text="Отмена", callback_data="reg:cancel"),
        ],
    ])


def _kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отправить заявку", callback_data="reg:submit")],
        [InlineKeyboardButton(text="Отмена", callback_data="reg:cancel")],
    ])


def _is_username_unique(username: str, store_path: str) -> bool:
    users_dir = Path(store_path) / "users"
    if not users_dir.is_dir():
        return True
    for file in users_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text())
            if data.get("username", "").lower() == username.lower():
                return False
        except (json.JSONDecodeError, OSError):
            pass
    return True


def _is_telegram_id_unique(telegram_id: int, store_path: str) -> bool:
    users_dir = Path(store_path) / "users"
    if not users_dir.is_dir():
        return True
    for file in users_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text())
            if data.get("telegram_id") == telegram_id:
                return False
        except (json.JSONDecodeError, OSError):
            pass
    return True


def _confirm_text(username: str, email: str | None) -> str:
    email_line = f"Email: {email}" if email else "Email: не указан"
    return (
        "Проверьте данные перед отправкой:\n\n"
        f"Никнейм: {username}\n"
        f"{email_line}\n\n"
        "Всё верно?"
    )


# ---------------------------------------------------------------------------
# /reg — точка входа
# ---------------------------------------------------------------------------

@router.message(Command("reg"), StateFilter(DEFAULT_STATE))
async def cmd_reg(message: Message, state: FSMContext, role: Role) -> None:
    if role != Role.GUEST:
        await message.answer("Вы уже зарегистрированы в системе.")
        return

    await state.set_state(RegStates.waiting_username)
    await message.answer(
        "Регистрация в Sigil Gate.\n\nВведите ваш никнейм:",
        reply_markup=_kb_cancel(),
    )


# ---------------------------------------------------------------------------
# Шаг 1: никнейм
# ---------------------------------------------------------------------------

@router.message(RegStates.waiting_username)
async def reg_username(message: Message, state: FSMContext,
                       store_path: str) -> None:
    username = (message.text or "").strip()

    if not username:
        await message.answer("Никнейм не может быть пустым. Попробуйте ещё раз:",
                              reply_markup=_kb_cancel())
        return

    if not _is_username_unique(username, store_path):
        await message.answer("Этот никнейм уже занят. Введите другой:",
                              reply_markup=_kb_cancel())
        return

    await state.update_data(username=username)
    await state.set_state(RegStates.waiting_email)
    await message.answer(
        "Введите email для связи (необязательно):",
        reply_markup=_kb_email(),
    )


# ---------------------------------------------------------------------------
# Шаг 2: email — ввод текстом
# ---------------------------------------------------------------------------

@router.message(RegStates.waiting_email)
async def reg_email(message: Message, state: FSMContext) -> None:
    email = (message.text or "").strip()

    if not email:
        await message.answer("Введите email или нажмите «Пропустить»:",
                              reply_markup=_kb_email())
        return

    if "@" not in email or "." not in email.split("@")[-1]:
        await message.answer("Некорректный email. Попробуйте ещё раз или нажмите «Пропустить»:",
                              reply_markup=_kb_email())
        return

    await state.update_data(email=email)
    await state.set_state(RegStates.confirm)
    data = await state.get_data()
    await message.answer(_confirm_text(data["username"], email),
                         reply_markup=_kb_confirm())


# ---------------------------------------------------------------------------
# Шаг 2: email — кнопка «Пропустить»
# ---------------------------------------------------------------------------

@router.callback_query(RegStates.waiting_email, F.data == "reg:skip_email")
async def reg_skip_email(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(email=None)
    await state.set_state(RegStates.confirm)
    data = await state.get_data()
    await callback.message.edit_text(_confirm_text(data["username"], None),
                                     reply_markup=_kb_confirm())
    await callback.answer()


# ---------------------------------------------------------------------------
# Шаг 3: подтверждение и отправка
# ---------------------------------------------------------------------------

@router.callback_query(RegStates.confirm, F.data == "reg:submit")
async def reg_submit(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    store_path: str,
    scripts_path: str,
    default_core_node: str,
    admin_ids: set,
    verbose: bool,
) -> None:
    tg_user = callback.from_user
    data = await state.get_data()
    username: str = data["username"]
    email: str | None = data.get("email")

    # Повторная проверка уникальности по telegram_id (на случай гонки)
    if not _is_telegram_id_unique(tg_user.id, store_path):
        await state.clear()
        await callback.message.edit_text(
            "Вы уже подали заявку ранее. Ожидайте решения администратора."
        )
        await callback.answer()
        return

    # Формируем команду create.sh
    cmd_create = [
        f"{scripts_path}/users/create.sh",
        "--username", username,
        "--core-node", default_core_node,
        "--status", "inactive",
        "--telegram-id", str(tg_user.id),
    ]
    if tg_user.username:
        cmd_create += ["--telegram", f"@{tg_user.username}"]
    if email:
        cmd_create += ["--email", email]

    rc, stdout, stderr = await run_script(
        cmd_create,
        send=callback.message.answer,
        verbose=verbose,
    )

    if rc != 0:
        logger.error("users/create.sh failed: %s", stderr)
        await callback.message.edit_text(
            "Произошла ошибка при отправке заявки. Попробуйте позже."
        )
        await state.clear()
        await callback.answer()
        return

    user_id = stdout.strip()

    cmd_commit = [
        f"{scripts_path}/store/commit.sh",
        "--message", f"Reg request: {username} (ID: {user_id}) via Telegram",
    ]
    await run_script(cmd_commit, send=callback.message.answer, verbose=verbose)

    await state.clear()
    await callback.message.edit_text(
        "Ваша заявка направлена администратору и будет рассмотрена в ближайшее время."
    )
    await callback.answer()

    # Уведомление администраторов
    tg_name = f"@{tg_user.username}" if tg_user.username else f"id={tg_user.id}"
    notify = f"Поступила заявка на подключение от пользователя {username} ({tg_name})"
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, notify)
        except Exception as e:
            logger.warning("Failed to notify admin %s: %s", admin_id, e)


# ---------------------------------------------------------------------------
# Отмена из любого состояния регистрации
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(RegStates), F.data == "reg:cancel")
async def reg_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Регистрация отменена.")
    await callback.answer()
