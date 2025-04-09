import logging
from datetime import datetime, timezone, time

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import StateFilter, Command
from aiogram.utils.markdown import hbold
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy.ext.asyncio import AsyncSession

from keyboards import inline, reply
from database import crud
from services import user_service
from utils.date_time_helpers import parse_horoscope_time
from states.user_states import HoroscopeTimeInput
from core.config import settings, PAID_SERVICES, SERVICE_NATAL_CHART

horoscope_router = Router()
logger = logging.getLogger(__name__)

@horoscope_router.message(F.text == "⏰ Ежедневный гороскоп")
async def cmd_daily_horoscope_settings(message: Message, session: AsyncSession, state: FSMContext):
    await state.clear(); user_id = message.from_user.id
    if not await user_service.has_natal_data(session, user_id):
        await message.answer(f"Нужны данные рождения. Сначала '🔮 {hbold(PAID_SERVICES[SERVICE_NATAL_CHART])}'.",
                             parse_mode="HTML", reply_markup=reply.get_main_menu(user_id)); return
    user = await crud.get_user(session, user_id)
    if not user: return
    current_time = user.daily_horoscope_time; markup = inline.create_horoscope_time_keyboard()
    if current_time: await message.answer(f"Гороскоп включен ({hbold(current_time)} UTC).\nИзменить/отключить?", reply_markup=markup)
    else: await message.answer("Включить гороскоп?\nВыберите время (UTC):", reply_markup=markup)
    await state.set_state(HoroscopeTimeInput.waiting_for_time)

@horoscope_router.callback_query(HoroscopeTimeInput.waiting_for_time, F.data.startswith("set_horo_time:"))
async def handle_set_horoscope_time(callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id; action = callback.data.split(":", 1)[1]; new_time: Optional[str] = None; msg_txt = ""
    if action == "disable": new_time = None; msg_txt = "Гороскоп отключен."; logger.info(f"Horoscope disabled user {user_id}")
    else:
        if parse_horoscope_time(action): new_time = action; msg_txt = f"Гороскоп будет приходить в {hbold(new_time)} UTC."; logger.info(f"Horoscope time {new_time} UTC set user {user_id}")
        else: await callback.answer("Неверный формат времени.", show_alert=True); return
    success = await crud.set_daily_horoscope_time(session, user_id, new_time); await state.clear()
    if success:
        try: await callback.message.edit_text(msg_txt, parse_mode="HTML")
        except TelegramBadRequest: pass
    else: await callback.answer("Ошибка сохранения.", show_alert=True)
    try: await callback.answer()
    except Exception: pass
    await callback.message.answer("Главное меню:", reply_markup=reply.get_main_menu(user_id))

@horoscope_router.message(HoroscopeTimeInput.waiting_for_time)
async def handle_text_cancel_horoscope_time(message: Message, state: FSMContext):
     await state.clear(); await message.answer("Выбор отменен.", reply_markup=reply.get_main_menu(message.from_user.id))