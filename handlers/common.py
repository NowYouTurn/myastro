import logging
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, FSInputFile, User # Добавлен User
from aiogram.utils.markdown import hlink, hbold
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from sqlalchemy.ext.asyncio import AsyncSession

from keyboards import reply, inline
from core.config import settings, PAID_SERVICES, SERVICE_COST # Используем Pydantic settings
from database import crud
from services.user_service import notify_user # get_user_or_register не используется
from states.user_states import TermsAgreement
from utils.referral_utils import generate_referral_link

common_router = Router()
logger = logging.getLogger(__name__)

# --- Обработка команды /start ---
@common_router.message(CommandStart())
async def handle_start(message: Message, session: AsyncSession, state: FSMContext, bot: Bot):
    await state.clear()
    aiogram_user: User = message.from_user # Получаем объект пользователя Aiogram
    args = message.text.split()
    referrer_code = args[1] if len(args) > 1 else None
    referrer_id = None

    if referrer_code:
        referrer = await crud.get_user_by_referral_code(session, referrer_code)
        if referrer and referrer.id != aiogram_user.id:
            referrer_id = referrer.id; logger.info(f"User {aiogram_user.id} started via ref {referrer_code} from {referrer_id}")
        elif referrer: logger.info(f"User {aiogram_user.id} used own ref code '{referrer_code}'.")
        else: logger.warning(f"Invalid ref code '{referrer_code}' used by {aiogram_user.id}")

    # Создаем или обновляем пользователя в БД
    db_user = await crud.create_or_update_user(
        session=session, user_id=aiogram_user.id, username=aiogram_user.username,
        first_name=aiogram_user.first_name, last_name=aiogram_user.last_name,
        language_code=aiogram_user.language_code, referrer_id=referrer_id )

    if not db_user: logger.error(f"Failed create/update user {aiogram_user.id}"); await message.answer("Ошибка профиля."); return

    user_name = db_user.first_name or "Пользователь"

    # Проверка принятия условий
    if not db_user.accepted_terms:
        logger.info(f"User {db_user.id} needs terms agreement.")
        legal_notice_text = settings.LEGAL_NOTICE # Берем из настроек
        await message.answer( f"👋 Добро пожаловать, {hbold(user_name)}!\n\n"
            f"Я ваш персональный астро-эзотерический помощник.\n\n{settings.ACCEPT_TERMS_PROMPT}",
            reply_markup=ReplyKeyboardRemove() )
        await message.answer( legal_notice_text, reply_markup=inline.get_accept_terms_keyboard(),
            parse_mode="HTML", disable_web_page_preview=True )
        await state.set_state(TermsAgreement.waiting_for_agreement)
    else:
        logger.info(f"User {db_user.id} already accepted. Show main menu.")
        await message.answer( f"👋 С возвращением, {hbold(user_name)}!\nЧем помочь?",
            reply_markup=reply.get_main_menu(db_user.id) )


# --- Обработка принятия условий ---
@common_router.callback_query(TermsAgreement.waiting_for_agreement, F.data == "accept_terms")
async def handle_accept_terms(callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id; user_name = callback.from_user.first_name or "Пользователь"
    success = await crud.set_user_accepted_terms(session, user_id)
    await state.clear()

    if success:
        logger.info(f"User {user_id} accepted terms.")
        try:
            await callback.message.edit_text(f"Спасибо, {hbold(user_name)}! Условия приняты.\nИспользуйте меню.", parse_mode="HTML")
            await callback.message.answer("Главное меню:", reply_markup=reply.get_main_menu(user_id))
        except TelegramBadRequest as e:
             if "message is not modified" in str(e): await callback.answer("Условия уже приняты.")
             else: logger.error(f"Error editing msg on terms accept user {user_id}: {e}"); await callback.message.answer("Условия приняты!\nГлавное меню:", reply_markup=reply.get_main_menu(user_id))
        except Exception as e: logger.exception(f"Unexpected error on terms accept user {user_id}: {e}"); await callback.answer("Произошла ошибка.")
    else:
        logger.error(f"Failed set terms flag user {user_id}")
        await callback.answer("Ошибка сохранения согласия.", show_alert=True)
    # Отвечаем на колбек в любом случае (если не было ответа ранее)
    try: await callback.answer()
    except Exception: pass


# --- Обработка команды /help ---
@common_router.message(Command("help"))
@common_router.message(F.text == "ℹ️ Помощь")
async def handle_help(message: Message, session: AsyncSession, state: FSMContext, bot: Bot):
     user = await crud.get_user(session, message.from_user.id)
     user_name = message.from_user.first_name or "Пользователь"
     if not user or not user.accepted_terms: await handle_start(message, session, state, bot); return

     help_text = f"""
Привет, {hbold(user_name)}! Я умею:

🔮 {hbold("Натальная карта:")} Расчет и интерпретация карты рождения.
✨ {hbold("Прогноз на год:")} Общий прогноз по сферам жизни.
💖 {hbold("Совместимость:")} Анализ карт двух людей + %.
🌙 {hbold("Толкование сна:")} Интерпретация ваших снов.
🍀 {hbold("Приметы и Эзотерика:")} Значения примет и явлений.
✋ {hbold("Хиромантия:")} Базовый анализ по фото ладоней (ИИ).
⏰ {hbold("Ежедневный гороскоп:")} Настройка ежедневной рассылки (бесплатно).
💰 {hbold("Баланс и Покупка:")} Баланс ({user.credits} кр.) и покупка кредитов ({settings.service_cost} кр./услуга). Первая услуга - бесплатно!
🎁 {hbold("Реферальная программа:")} Бонусы за друзей (за их первую беспл. услугу).

Используйте кнопки меню. /start для перезапуска.
Вопросы по оплате/возвратам: {settings.refund_contact_email}
"""
     await message.answer(help_text, reply_markup=reply.get_main_menu(user.id), parse_mode="HTML")

# --- Обработка команды /menu ---
@common_router.message(Command("menu"))
async def handle_menu_command(message: Message, session: AsyncSession, state: FSMContext, bot: Bot): # Добавлен bot
    await state.clear()
    user = await crud.get_user(session, message.from_user.id)
    if not user or not user.accepted_terms: await handle_start(message, session, state, bot); return
    await message.answer("Главное меню:", reply_markup=reply.get_main_menu(user.id))

# --- Обработка отмены ---
@common_router.callback_query(F.data.in_({"cancel_service", "fsm_cancel", "cancel_palmistry", "cancel_payment"})) # Объединили отмены
async def handle_cancel_action(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state(); user_id = callback.from_user.id
    action_text = "Действие отменено."
    if callback.data == "cancel_payment": action_text = "Покупка отменена."
    elif callback.data == "cancel_palmistry": action_text = "Анализ ладоней отменен."
    elif callback.data == "cancel_service": action_text = "Выбор услуги отменен."

    if current_state is not None:
        logger.info(f"User {user_id} отменил действие из {current_state}")
        await state.clear()
    try: await callback.message.edit_text(action_text)
    except TelegramBadRequest: pass # Игнор "not modified"
    # Показываем главное меню новым сообщением
    await callback.message.answer("Главное меню:", reply_markup=reply.get_main_menu(user_id))
    await callback.answer()

# --- Обработка dummy кнопок ---
@common_router.callback_query(F.data.startswith("dummy_"))
async def handle_dummy_callback(callback: CallbackQuery):
    text = {"dummy_nocredits": "Недостаточно кредитов.", "dummy_nopdf": "Пример недоступен."}.get(callback.data, "Инфо")
    await callback.answer(text, show_alert=False)

# --- Просмотр PDF примера ---
@common_router.callback_query(F.data.startswith("show_pdf_example:"))
async def handle_show_pdf_example(callback: CallbackQuery, session: AsyncSession): # session не нужна
    service_id = callback.data.split(":", 1)[1]; service_name = PAID_SERVICES.get(service_id, "?")
    pdf_path = settings.pdf_dir / f"{service_id}_example.pdf"
    if pdf_path.exists():
        try:
            pdf_file = FSInputFile(pdf_path, filename=f"{service_id}_example.pdf")
            await callback.message.answer_document(pdf_file, caption=f"📄 Пример '{service_name}'.")
            await callback.answer()
        except TelegramAPIError as e: logger.error(f"Ошибка PDF user {callback.from_user.id}: {e}"); await callback.answer("Ошибка отправки файла.", show_alert=True)
        except Exception as e: logger.exception(f"Ошибка PDF {pdf_path}: {e}"); await callback.answer("Ошибка файла.", show_alert=True)
    else: logger.warning(f"PDF не найден: {pdf_path}"); await callback.answer(f"Пример для '{service_name}' не найден.", show_alert=True)

# --- Обработка неизвестных сообщений (должен быть последним) ---
@common_router.message(StateFilter(None), ~CommandStart()) # Ловим все, кроме /start, вне состояний
async def handle_unknown_message(message: Message, session: AsyncSession, state: FSMContext, bot: Bot):
    user = await crud.get_user(session, message.from_user.id)
    if not user or not user.accepted_terms: await handle_start(message, session, state, bot); return
    logger.debug(f"Unknown message user {message.from_user.id}: {message.text[:50]}")
    await message.reply("Не понимаю вас. 🤔 Используйте кнопки меню или /help.", reply_markup=reply.get_main_menu(message.from_user.id))