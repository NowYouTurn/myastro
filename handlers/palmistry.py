import logging
import io
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import StateFilter, Command
from aiogram.utils.markdown import hbold
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from sqlalchemy.ext.asyncio import AsyncSession

# Используем Pydantic settings
from core.config import settings, PAID_SERVICES, SERVICE_PALMISTRY, SERVICE_COST, PALMISTRY_DISCLAIMER

from states.user_states import PalmistryInput
from keyboards import inline, reply
from database import crud
from services import user_service, openai_service, referral_service # Добавлен referral_service

palmistry_router = Router()
logger = logging.getLogger(__name__)

# --- Хиромантия ---
@palmistry_router.message(F.text == "✋ Хиромантия (Фото рук)")
async def cmd_palmistry(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    user_id = message.from_user.id
    can_use, credits, is_free, check_msg = await user_service.check_service_availability(session, user_id)
    if not can_use: await message.answer(check_msg, reply_markup=inline.get_payment_options_keyboard()); return

    confirm_text = (f"✨ Услуга: {hbold(PAID_SERVICES[SERVICE_PALMISTRY])}.\n{check_msg}\n\n"
                    f"{PALMISTRY_DISCLAIMER}\n\nХотите продолжить?")
    markup = inline.get_confirm_service_keyboard(SERVICE_PALMISTRY, settings.service_cost if not is_free else 0, credits)
    await message.answer(confirm_text, reply_markup=markup, parse_mode="HTML")

# Подтверждение услуги
@palmistry_router.callback_query(F.data == f"confirm_service:{SERVICE_PALMISTRY}")
async def handle_confirm_palmistry_service(
    callback: CallbackQuery, 
    state: FSMContext, 
    session: AsyncSession
):
    user_id = callback.from_user.id
    can_use, _, is_free, _ = await user_service.check_service_availability(session, user_id)
    
    if not can_use:
        await callback.answer("Нет кредитов.", show_alert=True)
        try:
            await callback.message.edit_text(
                "Нет кредитов.", 
                reply_markup=inline.get_payment_options_keyboard()
            )
        except TelegramBadRequest:
            pass
        return

    await state.update_data(is_free=is_free)
    
    try:
        await callback.message.edit_text(
            f"Пришлите фото {hbold('ЛЕВОЙ')} ладони:",
            reply_markup=inline.get_cancel_keyboard("cancel_palmistry"),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    
    await state.set_state(PalmistryInput.waiting_for_left_hand)
    await callback.answer()

# Получение фото левой руки
@palmistry_router.message(PalmistryInput.waiting_for_left_hand, F.photo)
async def handle_left_hand_photo(message: Message, state: FSMContext, bot: Bot):
    if not message.photo: await message.reply("Ошибка: Фото не найдено.", reply_markup=inline.get_cancel_keyboard("cancel_palmistry")); return
    photo = message.photo[-1]; photo_data = io.BytesIO()
    try: await bot.download(photo, destination=photo_data); photo_bytes = photo_data.getvalue(); assert photo_bytes
    except Exception as e: logger.exception(f"Ошибка скач. фото Л руки user {message.from_user.id}: {e}"); await message.reply("Не удалось загрузить. Попробуйте еще раз.", reply_markup=inline.get_cancel_keyboard("cancel_palmistry")); return
    finally: photo_data.close()

    await state.update_data(left_hand_photo=photo_bytes)
    await message.answer(f"Фото Л ({len(photo_bytes) // 1024} КБ) получено.\nТеперь пришлите фото {hbold('ПРАВОЙ')} ладони.",
                         reply_markup=inline.get_cancel_keyboard("cancel_palmistry"), parse_mode="HTML")
    await state.set_state(PalmistryInput.waiting_for_right_hand)

# Текст вместо фото Л руки
@palmistry_router.message(PalmistryInput.waiting_for_left_hand)
async def handle_text_instead_of_left_photo(message: Message):
     await message.reply("Пришлите именно ФОТО левой ладони.", reply_markup=inline.get_cancel_keyboard("cancel_palmistry"))

# Получение фото правой руки и запуск анализа
@palmistry_router.message(PalmistryInput.waiting_for_right_hand, F.photo)
async def handle_right_hand_photo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    if not message.photo: await message.reply("Ошибка: Фото не найдено.", reply_markup=inline.get_cancel_keyboard("cancel_palmistry")); return
    photo = message.photo[-1]; photo_data = io.BytesIO(); user_id = message.from_user.id
    try: await bot.download(photo, destination=photo_data); photo_bytes_right = photo_data.getvalue(); assert photo_bytes_right
    except Exception as e: logger.exception(f"Ошибка скач. фото П руки user {user_id}: {e}"); await message.reply("Не удалось загрузить. Попробуйте еще раз.", reply_markup=inline.get_cancel_keyboard("cancel_palmistry")); return
    finally: photo_data.close()

    data = await state.get_data(); photo_bytes_left = data.get('left_hand_photo')
    if not photo_bytes_left: logger.error(f"Фото Л руки не найдено в FSM user {user_id}"); await state.clear(); await message.answer("Ошибка. Начните заново.", reply_markup=reply.get_main_menu(user_id)); return

    await state.clear()
    proc_msg = await message.answer(f"Фото П ({len(photo_bytes_right) // 1024} КБ) получено.\n✋ Анализирую...", reply_markup=ReplyKeyboardRemove())
    await bot.send_chat_action(chat_id=user_id, action="typing")

    # --- Списываем кредит / используем бесплатную ---
    is_free = data.get("is_free", False); service_used = False
    if not is_free:
        if await user_service.use_service_credit(session, user_id): service_used = True
        else: logger.error(f"Ошибка списания user {user_id} за {SERVICE_PALMISTRY}"); await proc_msg.edit_text("Ошибка оплаты.", reply_markup=reply.get_main_menu(user_id)); return
    else:
        if await crud.mark_first_service_used(session, user_id):
            logger.info(f"Исп. беспл. {SERVICE_PALMISTRY} user {user_id}"); service_used = True
            await referral_service.award_referral_bonus_if_applicable(session, bot, user_id) # Проверка бонуса
        else: logger.error(f"Ошибка отметки беспл. user {user_id} для {SERVICE_PALMISTRY}"); await proc_msg.edit_text("Ошибка.", reply_markup=reply.get_main_menu(user_id)); return
    if not service_used: return
    # --- Конец списания / использования ---

    analysis = await openai_service.get_palmistry_analysis(photo_bytes_left, photo_bytes_right)
    await proc_msg.edit_text(analysis, parse_mode="HTML", disable_web_page_preview=True)
    await message.answer("Выберите следующее действие:", reply_markup=reply.get_main_menu(user_id))

# Текст вместо фото П руки
@palmistry_router.message(PalmistryInput.waiting_for_right_hand)
async def handle_text_instead_of_right_photo(message: Message):
     await message.reply("Пришлите именно ФОТО правой ладони.", reply_markup=inline.get_cancel_keyboard("cancel_palmistry"))