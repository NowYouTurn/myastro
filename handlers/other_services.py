import logging
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, User # Добавлен User
from aiogram.filters import StateFilter
from aiogram.utils.markdown import hbold
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings, PAID_SERVICES, SERVICE_DREAM, SERVICE_SIGNS, SERVICE_COST
from states.user_states import DreamInput, SignsInput
from keyboards import inline, reply
from database import crud
from services import user_service, openai_service, referral_service # Добавлен referral_service

other_services_router = Router()
logger = logging.getLogger(__name__)

# --- Вспомогательные функции ---
async def use_credit_or_free(session: AsyncSession, bot: Bot, user_id: int, is_free: bool, service_id: str) -> bool:
    if not is_free:
        if not await user_service.use_service_credit(session, user_id): logger.error(f"Ошибка списания user {user_id} за {service_id}"); return False
        else: return True
    else:
        if not await crud.mark_first_service_used(session, user_id): logger.error(f"Ошибка отметки free user {user_id} для {service_id}"); return False
        else: logger.info(f"Исп. беспл. {service_id} user {user_id}"); await referral_service.award_referral_bonus_if_applicable(session, bot, user_id); return True

async def start_other_service(m: Message, state: FSMContext, session: AsyncSession, sid: str):
    await state.clear(); uid = m.from_user.id
    can_use, creds, is_free, chk_msg = await user_service.check_service_availability(session, uid)
    if not can_use: await m.answer(chk_msg, reply_markup=inline.get_payment_options_keyboard()); return
    cost = settings.service_cost if not is_free else 0
    txt = f"✨ Услуга: {hbold(PAID_SERVICES[sid])}.\n{chk_msg}\nПродолжить?"
    markup = inline.get_confirm_service_keyboard(sid, cost, creds)
    await m.answer(txt, reply_markup=markup, parse_mode="HTML")

async def process_confirm_other_service(
    c: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    sid: str,
    prompt: str,
    nxt_state: StateFilter
):
    uid = c.from_user.id
    can_use, _, is_free, _ = await user_service.check_service_availability(session, uid)
    
    if not can_use:
        await c.answer("Нет кредитов.", show_alert=True)
        try:
            await c.message.edit_text(
                "Нет кредитов.", 
                reply_markup=inline.get_payment_options_keyboard()
            )
        except TelegramBadRequest:
            pass
        return

    await state.update_data(is_free=is_free)
    
    try:
        await c.message.edit_text(
            prompt,
            reply_markup=inline.get_cancel_keyboard()
        )
    except TelegramBadRequest:
        pass
    
    await state.set_state(nxt_state)
    await c.answer()

# --- Толкование сна ---
@other_services_router.message(F.text == "🌙 Толкование сна")
async def cmd_dream(m: Message, state: FSMContext, session: AsyncSession): await start_other_service(m, state, session, SERVICE_DREAM)
@other_services_router.callback_query(F.data == f"confirm_service:{SERVICE_DREAM}")
async def confirm_dream(c: CallbackQuery, state: FSMContext, session: AsyncSession): await process_confirm_other_service(c, state, session, SERVICE_DREAM, "Опишите ваш сон:", DreamInput.waiting_for_dream_text)
@other_services_router.message(DreamInput.waiting_for_dream_text, F.text)
async def handle_dream(m: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    txt = m.text; uid = m.from_user.id
    if not txt or len(txt.split()) < 3: await m.reply("Опишите подробнее (мин. 3 слова).", reply_markup=inline.get_cancel_keyboard()); return
    data = await state.get_data(); await state.clear()
    proc_msg = await m.answer("🌙 Анализирую...", reply_markup=ReplyKeyboardRemove())
    await bot.send_chat_action(chat_id=uid, action="typing")
    if not await use_credit_or_free(session, bot, uid, data.get("is_free", False), SERVICE_DREAM): await proc_msg.edit_text("Ошибка оплаты.", reply_markup=reply.get_main_menu(uid)); return
    interp = await openai_service.get_dream_interpretation(txt); await proc_msg.edit_text(interp, parse_mode="HTML", disable_web_page_preview=True)
    await m.answer("Выберите действие:", reply_markup=reply.get_main_menu(uid))
@other_services_router.message(DreamInput.waiting_for_dream_text)
async def dream_wrong_input(m: Message): await m.reply("Опишите сон текстом.", reply_markup=inline.get_cancel_keyboard())

# --- Приметы и Эзотерика ---
@other_services_router.message(F.text == "🍀 Приметы и Эзотерика")
async def cmd_signs(m: Message, state: FSMContext, session: AsyncSession): await start_other_service(m, state, session, SERVICE_SIGNS)
@other_services_router.callback_query(F.data == f"confirm_service:{SERVICE_SIGNS}")
async def confirm_signs(c: CallbackQuery, state: FSMContext, session: AsyncSession): await process_confirm_other_service(c, state, session, SERVICE_SIGNS, "О какой примете узнать?", SignsInput.waiting_for_sign_text)
@other_services_router.message(SignsInput.waiting_for_sign_text, F.text)
async def handle_signs(m: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    txt = m.text; uid = m.from_user.id
    if not txt or len(txt) < 3: await m.reply("Сформулируйте вопрос (мин. 3 симв).", reply_markup=inline.get_cancel_keyboard()); return
    data = await state.get_data(); await state.clear()
    proc_msg = await m.answer("🍀 Ищу информацию...", reply_markup=ReplyKeyboardRemove())
    await bot.send_chat_action(chat_id=uid, action="typing")
    if not await use_credit_or_free(session, bot, uid, data.get("is_free", False), SERVICE_SIGNS): await proc_msg.edit_text("Ошибка оплаты.", reply_markup=reply.get_main_menu(uid)); return
    interp = await openai_service.get_sign_interpretation(txt); await proc_msg.edit_text(interp, parse_mode="HTML", disable_web_page_preview=True)
    await m.answer("Выберите действие:", reply_markup=reply.get_main_menu(uid))
@other_services_router.message(SignsInput.waiting_for_sign_text)
async def signs_wrong_input(m: Message): await m.reply("Введите вопрос текстом.", reply_markup=inline.get_cancel_keyboard())