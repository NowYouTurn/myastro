import logging
import asyncio
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import StateFilter, Command, Filter
from aiogram.utils.markdown import hbold, hcode
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy.ext.asyncio import AsyncSession

from keyboards import reply, inline
from database import crud
from database.models import LogLevel, User # Добавлен User
from services import user_service, payment_service, admin_service
from core.config import settings
from states.user_states import AdminActions

admin_router = Router()
logger = logging.getLogger(__name__)

# --- Фильтр IsAdmin ---
class IsAdmin(Filter):
    async def __call__(self, m_or_c: Message | CallbackQuery) -> bool:
        return m_or_c.from_user.id in settings.admin_ids

# --- Утилита поиска пользователя ---
async def find_user_by_query(session: AsyncSession, query: str) -> Optional[User]:
    user = None
    try: user = await crud.get_user(session, int(query))
    except (ValueError, TypeError):
        username = query.lstrip('@')
        if username: user = await crud.get_user_by_username(session, username)
    return user

# --- Вход / Выход / Отмена ---
@admin_router.message(IsAdmin(), F.text == "👑 Админ-панель")
@admin_router.message(IsAdmin(), Command("admin"))
async def cmd_admin_panel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("👑 Админ-панель:", reply_markup=reply.get_admin_menu())

async def back_to_admin_menu(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("👑 Админ-панель:", reply_markup=reply.get_admin_menu())

@admin_router.message(IsAdmin(), F.text == "⬅️ Назад в главное меню")
async def cmd_back_to_main(m: Message, state: FSMContext):
    from handlers.common import handle_menu_command
    await handle_menu_command(m, state, m.bot)

@admin_router.callback_query(StateFilter(AdminActions), F.data == "fsm_cancel")
async def cancel_admin(c: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    logger.info(f"Admin {c.from_user.id} отменил {current_state}")
    await state.clear()
    try:
        await c.message.edit_text("Действие отменено.")
    except TelegramBadRequest:
        await c.message.delete()
        await c.message.answer("Действие отменено.")
    await c.message.answer("👑 Админ-панель:", reply_markup=reply.get_admin_menu())
    await c.answer()

# --- Статистика ---
@admin_router.message(IsAdmin(), F.text == "📊 Статистика")
async def cmd_stats(m: Message, session: AsyncSession): await m.answer(await admin_service.generate_statistics_report(session), parse_mode="HTML")

# --- Поиск Пользователя ---
@admin_router.message(IsAdmin(), F.text == "👤 Найти пользователя")
async def find_user_start(m: Message, state: FSMContext):
    await m.answer("Введите ID или Username:", reply_markup=inline.get_cancel_keyboard())
    await state.set_state(AdminActions.waiting_for_user_query_info)

@admin_router.message(IsAdmin(), AdminActions.waiting_for_user_query_info)
async def find_user_process(m: Message, state: FSMContext, session: AsyncSession):
    user = await find_user_by_query(session, m.text.strip())
    if user:
        await state.clear()
        natal = await crud.get_natal_data(session, user.id)
        payments = await crud.get_user_payments(session, user.id, 10)
        logs = await crud.get_user_logs(session, user.id, 20)

        info = await admin_service.format_user_info(user, natal, len(payments), len(logs))
        await m.answer(info, parse_mode="HTML")

        if payments:
            await m.answer(admin_service.format_payment_list(payments), parse_mode="HTML")
        if logs:
            try:
                await m.answer(admin_service.format_log_list(logs), parse_mode="HTML")
            except TelegramBadRequest:
                await m.answer("📄 Логи слишком длинные.")

        await m.answer("👑 Админ-панель:", reply_markup=reply.get_admin_menu())
    else:
        await m.reply("Не найден. Попробуйте еще.", reply_markup=inline.get_cancel_keyboard())

# --- Управление Кредитами ---
@admin_router.message(IsAdmin(), F.text == "💰 Управление кредитами")
async def credits_start(m: Message, state: FSMContext): await m.answer("Введите ID или Username:", reply_markup=inline.get_cancel_keyboard()); await state.set_state(AdminActions.waiting_for_user_query_credits)
@admin_router.message(IsAdmin(), AdminActions.waiting_for_user_query_credits)
async def credits_user(m: Message, state: FSMContext, session: AsyncSession):
    user = await find_user_by_query(session, m.text.strip())
    if user: await state.update_data(uid=user.id, uname=user.first_name, creds=user.credits); await m.answer(f"User: {user.first_name}(<code>{user.id}</code>), Баланс: {user.credits}\nВведите сумму (+/-):", reply_markup=inline.get_cancel_keyboard(), parse_mode="HTML"); await state.set_state(AdminActions.waiting_for_credits_amount)
    else: await m.reply("Не найден.", reply_markup=inline.get_cancel_keyboard())
@admin_router.message(IsAdmin(), AdminActions.waiting_for_credits_amount)
async def credits_amount(m: Message, state: FSMContext):
    try: amount = int(m.text); assert amount != 0
    except(ValueError, AssertionError): await m.reply("Неверная сумма (нужно != 0).", reply_markup=inline.get_cancel_keyboard()); return
    await state.update_data(change=amount); await m.answer(f"Сумма: {amount:+}. Причина:", reply_markup=inline.get_cancel_keyboard()); await state.set_state(AdminActions.waiting_for_reason_credits)
@admin_router.message(IsAdmin(), AdminActions.waiting_for_reason_credits)
async def credits_reason(m: Message, state: FSMContext):
    reason = m.text.strip()
    if not reason or len(reason) < 3: await m.reply("Причина < 3 симв.", reply_markup=inline.get_cancel_keyboard()); return
    await state.update_data(reason=reason); data = await state.get_data(); amount = data.get('change',0); new_b = data.get('creds',0)+amount
    await m.answer(f"<b>Подтв.:</b>\nUser: {data.get('uname','?')}(<code>{data.get('uid','?')}</code>)\nИзм: {amount:+}\nНов. баланс: {new_b}\nПричина: {reason}\nОтправляем?", reply_markup=reply.get_admin_confirm_credits_keyboard(), parse_mode="HTML"); await state.set_state(AdminActions.waiting_for_confirmation_credits)
@admin_router.message(IsAdmin(), AdminActions.waiting_for_confirmation_credits, F.text == "✅ Подтвердить изменение")
async def credits_confirm(m: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data(); await state.clear(); uid = data.get('uid'); change = data.get('change'); reason = data.get('reason','-'); admin_id = m.from_user.id
    if uid is None or change is None: logger.error(f"Admin {admin_id}: Ошибка FSM credits."); await m.answer("Ошибка состояния.", reply_markup=reply.get_admin_menu()); return
    new_b = await crud.update_user_credits(session, uid, change)
    if new_b is not None:
        log_msg = f"Admin {admin_id} изменил баланс user {uid} на {change:+}. Причина: {reason}. Новый баланс: {new_b}"; logger.warning(log_msg); await crud.add_log_entry(session, LogLevel.WARNING, log_msg, uid, "admin_credits")
        await m.answer(f"✅ Баланс user {uid} изменен. Новый: {new_b}", reply_markup=ReplyKeyboardRemove())
        user_notify = f"Админ изменил баланс на {change:+}. Причина: {reason}. Баланс: {new_b}."; await user_service.notify_user(bot, uid, user_notify)
        await m.answer("👑 Админ-панель:", reply_markup=reply.get_admin_menu())
    else: await m.answer("❌ Ошибка изменения баланса.", reply_markup=reply.get_admin_menu())
@admin_router.message(IsAdmin(), AdminActions.waiting_for_confirmation_credits, F.text == "❌ Отмена")
async def credits_cancel(m: Message, state: FSMContext): await state.clear(); await m.answer("Изменение баланса отменено.", reply_markup=reply.get_admin_menu())

# --- Рассылка ---
@admin_router.message(IsAdmin(), F.text == "📢 Сделать рассылку")
async def broadcast_start(m: Message, state: FSMContext): await m.answer("Текст для рассылки (HTML):", reply_markup=inline.get_cancel_keyboard()); await state.set_state(AdminActions.waiting_for_broadcast_message)
@admin_router.message(IsAdmin(), AdminActions.waiting_for_broadcast_message)
async def broadcast_msg(m: Message, state: FSMContext): text = m.html_text; await state.update_data(bcast=text); await m.answer("--- Предпросмотр ---"); await m.answer(text, parse_mode="HTML", disable_web_page_preview=True); await m.answer("--- Конец ---\nОтправляем?", reply_markup=reply.get_confirmation_keyboard()); await state.set_state(AdminActions.waiting_for_broadcast_confirmation)
@admin_router.message(IsAdmin(), AdminActions.waiting_for_broadcast_confirmation, F.text == "✅ Да")
async def broadcast_confirm(m: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data(); await state.clear(); text = data.get("bcast"); admin_id = m.from_user.id
    if not text: logger.error(f"Admin {admin_id}: Текст рассылки не найден."); await m.answer("Ошибка.", reply_markup=reply.get_admin_menu()); return
    uids = await crud.get_all_user_ids(session)
    if not uids: await m.answer("Нет пользователей.", reply_markup=reply.get_admin_menu()); return
    await m.answer(f"Начинаю рассылку {len(uids)} пользователям...", reply_markup=ReplyKeyboardRemove()); logger.info(f"Admin {admin_id} начал рассылку {len(uids)}."); await crud.add_log_entry(session, LogLevel.INFO, f"Admin {admin_id} начал рассылку ({len(uids)})", handler="admin_bcast")
    s, f = 0, 0; start = asyncio.get_event_loop().time()
    for uid in uids: s += 1 if await user_service.notify_user(bot, uid, text) else (f := f + 1); await asyncio.sleep(0.1)
    dur = round(asyncio.get_event_loop().time() - start, 2); res = f"✅ Рассылка ({dur}с). Успех: {s}, Ошибки: {f}"; log_res = f"Рассылка Ad:{admin_id}. Успех:{s}, Ошибки:{f}."; logger.info(log_res); await crud.add_log_entry(session, LogLevel.INFO, log_res, handler="admin_bcast"); await m.answer(res, reply_markup=reply.get_admin_menu())
@admin_router.message(IsAdmin(), AdminActions.waiting_for_broadcast_confirmation, F.text == "❌ Нет")
async def broadcast_cancel(m: Message, state: FSMContext): await state.clear(); await m.answer("Рассылка отменена.", reply_markup=reply.get_admin_menu())

# --- Просмотр Логов ---
@admin_router.message(IsAdmin(), F.text == "📄 Логи бота/пользователя")
async def logs_start(m: Message, state: FSMContext): await m.answer("User ID для фильтра или 'все' (последние 50):", reply_markup=inline.get_cancel_keyboard()); await state.set_state(AdminActions.waiting_for_user_query_logs)
@admin_router.message(IsAdmin(), AdminActions.waiting_for_user_query_logs)
async def logs_process(m: Message, state: FSMContext, session: AsyncSession):
    q = m.text.strip().lower(); limit = 50; uid: Optional[int] = None
    if q != 'все':
        try: uid = int(q); assert await crud.get_user(session, uid)
        except (ValueError, AssertionError): await m.reply("Неверный ID или user не найден.", reply_markup=inline.get_cancel_keyboard()); return
    await state.clear(); target = f"user {uid}" if uid else "бота"; await m.answer(f"Загружаю {limit} логов {target}...")
    logs = await crud.get_user_logs(session, user_id=uid, limit=limit); text = admin_service.format_log_list(logs)
    try: await m.answer(text, parse_mode="HTML")
    except TelegramBadRequest: await m.answer(f"📄 Логи ({len(logs)}) слишком длинные.")
    except Exception as e: logger.error(f"Ошибка отправки логов админу: {e}"); await m.answer("Ошибка.")
    await m.answer("👑 Админ-панель:", reply_markup=reply.get_admin_menu())

# --- Проверка Платежа ЮKassa ---
@admin_router.message(IsAdmin(), F.text == "🔎 Проверить платеж ЮKassa")
async def check_pay_start(m: Message, state: FSMContext): await m.answer("Введите ID платежа ЮKassa:", reply_markup=inline.get_cancel_keyboard()); await state.set_state(AdminActions.waiting_for_payment_id_check)
@admin_router.message(IsAdmin(), AdminActions.waiting_for_payment_id_check)
async def check_pay_process(m: Message, state: FSMContext, session: AsyncSession):
    pid = m.text.strip()
    if not pid or len(pid) < 36: await m.reply("Неверный формат ID.", reply_markup=inline.get_cancel_keyboard()); return
    await state.clear(); await m.answer(f"Проверяю <code>{pid}</code>...", parse_mode="HTML")
    status, owner_id = await payment_service.check_yookassa_payment_status(session, pid)
    db_pay = await crud.get_payment_by_yookassa_id(session, pid)
    res = f"Статус <code>{pid}</code>:\n"
    if status:
        res += f"- ЮKassa: <b>{status.name}</b>\n"
        if db_pay: res += f"- БД: <b>{db_pay.status.name}</b> (Начисл:{'Да' if db_pay.credits_awarded else 'Нет'})\n- User:{db_pay.user_id} ({db_pay.amount/100}р, {db_pay.credits_purchased}кр)\n- Создан:{db_pay.created_at.strftime('%y-%m-%d %H:%M')}\n"
        else: res += "- <i>Не найден в БД.</i>\n"
    else: res += "<b>Не удалось получить статус от ЮKassa.</b>"
    await m.answer(res, parse_mode="HTML"); await m.answer("👑 Админ-панель:", reply_markup=reply.get_admin_menu())