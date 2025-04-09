import logging
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import StateFilter, Command
from aiogram.utils.markdown import hbold
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy.ext.asyncio import AsyncSession

from keyboards import inline, reply
from database import crud
from core.config import settings # Используем settings
from services import user_service, payment_service

payment_router = Router()
logger = logging.getLogger(__name__)

@payment_router.message(F.text == "💰 Баланс и Покупка")
async def cmd_balance(message: Message, session: AsyncSession):
    user_id = message.from_user.id; credits = await crud.get_user_credits(session, user_id); is_free = False
    if settings.first_service_free:
        user = await crud.get_user(session, user_id)
        if user and not user.first_service_used: is_free = True
    text = f"💰 Баланс: {hbold(credits)} кр.\n" + ("✨ Доступна 1 бесплатная услуга!" if is_free else "") + "\n\nВыберите пакет:"
    await message.answer(text, reply_markup=inline.get_payment_options_keyboard(), parse_mode="HTML")

@payment_router.callback_query(F.data == "buy_credits_menu")
async def cb_buy_credits_menu(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id; credits = await crud.get_user_credits(session, user_id)
    text = f"💰 Баланс: {hbold(credits)} кр.\n\nВыберите пакет:"
    try: await callback.message.edit_text(text, reply_markup=inline.get_payment_options_keyboard(), parse_mode="HTML")
    except TelegramBadRequest: pass
    await callback.answer()

@payment_router.callback_query(F.data.startswith("create_payment:"))
async def handle_create_payment(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    option_key = callback.data.split(":", 1)[1]; user_id = callback.from_user.id
    if option_key not in settings.PAYMENT_OPTIONS: await callback.answer("Неверная опция.", show_alert=True); return
    opt = settings.PAYMENT_OPTIONS[option_key]; amount = opt['price'] / 100; credits = opt['credits']
    try: await callback.message.edit_text(f"⏳ Создаю ссылку на оплату {opt['description']}...", reply_markup=None)
    except TelegramBadRequest: pass
    await callback.answer()
    url, p_id, err = await payment_service.create_yookassa_payment(session, user_id, amount, credits, option_key)
    if url and p_id:
        markup = inline.get_payment_link_keyboard(url) # Клавиатура БЕЗ проверки
        await callback.message.edit_text(f"✅ Ссылка создана!\n\nНажмите для оплаты.\nКредиты ({credits}) будут зачислены автоматически.", reply_markup=markup)
    else: await callback.message.edit_text(f"❌ Ошибка создания платежа.\n{err or 'Попробуйте позже.'}", reply_markup=inline.get_payment_options_keyboard())

# Обработчик отмены (перенесен в common.py)
# @payment_router.callback_query(F.data == "cancel_payment")
# async def handle_cancel_payment(callback: CallbackQuery, session: AsyncSession): pass