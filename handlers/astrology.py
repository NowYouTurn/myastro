import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, FSInputFile
from aiogram.filters import StateFilter
from aiogram.utils.markdown import hbold
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy.ext.asyncio import AsyncSession

from services.astrology_service import get_natal_data_kerykeion, KrInstance, generate_natal_chart_image, get_kr_instance_from_data

from core.config import (
    settings, PAID_SERVICES,
    SERVICE_NATAL_CHART, SERVICE_FORECAST, SERVICE_COMPATIBILITY,
    ASTROLOGY_DISCLAIMER, GEOCODING_DISCLAIMER
)
from states.user_states import NatalInput
from keyboards import inline, reply
from database import crud
from services import user_service, astrology_service, referral_service
from services.astrology_service import get_natal_data_kerykeion, KrInstance, generate_natal_chart_image
from utils.geocoding import get_coordinates_and_timezone
from utils.date_time_helpers import (
    get_available_years, is_valid_date, is_valid_time
)

astrology_router = Router()
logger = logging.getLogger(__name__)

# --- Общие функции FSM ---
async def start_astro_service(m_or_c: Message | CallbackQuery, state: FSMContext, session: AsyncSession, service_id: str):
    uid = m_or_c.from_user.id
    uname = m_or_c.from_user.first_name or "Пользователь"
    can_use, creds, is_free, chk_msg = await user_service.check_service_availability(session, uid)

    if not can_use:
        await m_or_c.answer(chk_msg, reply_markup=inline.get_payment_options_keyboard())
        return

    cost = settings.service_cost if not is_free else 0
    txt = f"✨ Услуга: {hbold(PAID_SERVICES[service_id])}.\n{chk_msg}\nПродолжить?"
    markup = inline.get_confirm_service_keyboard(service_id, cost, creds)

    if isinstance(m_or_c, Message):
        await m_or_c.answer(txt, reply_markup=markup, parse_mode="HTML")
    else:
        try:
            await m_or_c.message.edit_text(txt, reply_markup=markup, parse_mode="HTML")
        except TelegramBadRequest:
            await m_or_c.answer()

async def ask_for_year(m_or_c: Message | CallbackQuery, state: FSMContext, prefix: str = ""):
    years = get_available_years()
    markup = inline.create_calendar_years(years, f"{prefix}natal")
    lbl = f" {hbold('Партнера 2')}" if prefix else ""
    txt = f"📅 Выберите {hbold('год')} рождения{lbl}:"

    if isinstance(m_or_c, Message):
        # Убрали повторяющийся reply_markup и добавили ReplyKeyboardRemove
        await m_or_c.answer(
            txt, 
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()  # Если нужно убрать клавиатуру
        )
        # Отправляем инлайн-клавиатуру отдельным сообщением
        await m_or_c.answer(
            "Выберите год из списка:", 
            reply_markup=markup,
            parse_mode="HTML"
        )
    else:
        try:
            await m_or_c.message.edit_text(txt, reply_markup=markup, parse_mode="HTML")
        except TelegramBadRequest:
            # Добавили обработку исключения с ответом
            #await c.answer("Слишком частые запросы, попробуйте позже", show_alert=True)

         st = NatalInput.waiting_for_partner_year if prefix else NatalInput.waiting_for_year
    await state.set_state(st)

async def process_year_input(c: CallbackQuery, state: FSMContext, y: int, pre: str = ""):
    await state.update_data({f"{pre}year": y})
    m = inline.create_calendar_months(y, f"{pre}natal")
    l = "П2: " if pre else ""
    t = f"📅 Год {l}{y}. Выберите {hbold('месяц')}:"

    try:
        await c.message.edit_text(t, reply_markup=m, parse_mode="HTML")
    except TelegramBadRequest:
        # Добавили обработку исключения
        await c.answer("Не удалось обновить сообщение", show_alert=True)
    finally:
        # Всегда подтверждаем обработку callback
        await c.answer()

    st = NatalInput.waiting_for_partner_month if pre else NatalInput.waiting_for_month
    await state.set_state(st)
    await c.answer()

async def process_month_input(c: CallbackQuery, state: FSMContext, y: int, m: int, pre: str = ""):
    await state.update_data({f"{pre}month": m})
    markup = inline.create_calendar_days(y, m, f"{pre}natal")
    l = "П2: " if pre else ""
    t = f"📅 Дата {l}{m:02d}.{y}. Выберите {hbold('день')}:"

    try:
        await c.message.edit_text(t, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass

    st = NatalInput.waiting_for_partner_day if pre else NatalInput.waiting_for_day
    await state.set_state(st)
    await c.answer()

async def process_day_input(c: CallbackQuery, state: FSMContext, y: int, m: int, d: int, pre: str = ""):
    if not is_valid_date(y, m, d):
        await c.answer("Некорректный день!", show_alert=True)
        return

    await state.update_data({f"{pre}day": d})
    markup = inline.create_time_hours(y, m, d, f"{pre}natal")
    l = "П2: " if pre else ""
    t = f"📅 Дата {l}{d:02d}.{m:02d}.{y}. Выберите {hbold('час')}:"

    try:
        await c.message.edit_text(t, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass

    st = NatalInput.waiting_for_partner_hour if pre else NatalInput.waiting_for_hour
    await state.set_state(st)
    await c.answer()

async def process_hour_input(c: CallbackQuery, state: FSMContext, y: int, m: int, d: int, h: int, pre: str = ""):
    await state.update_data({f"{pre}hour": h})
    markup = inline.create_time_minutes(y, m, d, h, f"{pre}natal")
    l = "П2: " if pre else ""
    t = f"📅 Время {l}{d:02d}.{m:02d}.{y} {h:02d}:xx. Выберите {hbold('минуты')}:"

    try:
        await c.message.edit_text(t, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass

    st = NatalInput.waiting_for_partner_minute if pre else NatalInput.waiting_for_minute
    await state.set_state(st)
    await c.answer()

async def process_minute_input(c: CallbackQuery, state: FSMContext, y: int, m: int, d: int, h: int, mi: int, pre: str = ""):
    if not is_valid_time(h, mi):
        await c.answer("Некорректные минуты!", show_alert=True)
        return

    await state.update_data({f"{pre}minute": mi})
    l = f" {hbold('Партнера 2')}" if pre else ""
    t = f"📅 Дата и время{l}: {d:02d}.{m:02d}.{y} {h:02d}:{mi:02d}.\n\n🌍 Введите {hbold('город')} рождения{l}:"

    try:
        await c.message.edit_text(t, reply_markup=inline.get_cancel_keyboard(), parse_mode="HTML")
    except TelegramBadRequest:
        pass

    st = NatalInput.waiting_for_partner_city if pre else NatalInput.waiting_for_city
    await state.set_state(st)
    await c.answer()
async def process_city_input(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot, person_prefix: str = ""
):
    city = message.text.strip()
    if not city or len(city) < 2:
        await message.reply("Название города < 2 символов.", reply_markup=inline.get_cancel_keyboard())
        return

    user_id = message.from_user.id
    user_name = message.from_user.first_name or "?"

    await state.update_data({f"{person_prefix}city": city})
    data = await state.get_data()
    service_id = data.get("service_id")

    if not service_id:
        logger.error(f"No service_id in FSM state user {user_id}")
        await state.clear()
        await message.answer("Ошибка состояния.", reply_markup=reply.get_main_menu(user_id))
        return

    proc_msg = await message.answer(
        f"Ищем координаты '{city}'...\n<pre>{GEOCODING_DISCLAIMER}</pre>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )
    geo_result = await asyncio.to_thread(get_coordinates_and_timezone, city)

    if not geo_result:
        await proc_msg.edit_text(f"😔 Не найдены координаты '{city}'. Проверьте название.", reply_markup=inline.get_cancel_keyboard())
        return

    lat, lon, tz = geo_result
    await state.update_data({
        f"{person_prefix}latitude": lat,
        f"{person_prefix}longitude": lon,
        f"{person_prefix}timezone": tz
    })
    logger.info(f"Гео {city} ({'P2' if person_prefix else 'U' + str(user_id)}): {lat=}, {lon=}, {tz=}")

    date_str = f"{data.get(f'{person_prefix}day', '??'):02d}.{data.get(f'{person_prefix}month', '??'):02d}.{data.get(f'{person_prefix}year', '?')}"
    time_str = f"{data.get(f'{person_prefix}hour', '??'):02d}:{data.get(f'{person_prefix}minute', '??'):02d}"
    status_txt = f"👍 Данные {('П2' if person_prefix else '')}: {date_str} {time_str}, {city} (TZ:{tz})"

    if service_id == SERVICE_COMPATIBILITY and not person_prefix:
        try:
            await proc_msg.edit_text(status_txt + "\n\n⏳ Введите данные для Партнера 2.")
        except TelegramBadRequest:
            pass
        await ask_for_year(message, state, "partner_")
        return

    try:
        await proc_msg.edit_text(status_txt + f"\n\n⏳ Расчет {PAID_SERVICES[service_id]}...", parse_mode="HTML")
    except TelegramBadRequest:
        pass

    await bot.send_chat_action(chat_id=user_id, action="typing")
    final_data = await state.get_data()
    await state.clear()

    is_free = final_data.get("is_free", False)
    service_used = False

    if not is_free:
        if await user_service.use_service_credit(session, user_id):
            service_used = True
        else:
            logger.error(f"Ошибка списания user {user_id} за {service_id}")
            await message.answer("Ошибка оплаты.", reply_markup=reply.get_main_menu(user_id))
            return
    else:
        if await crud.mark_first_service_used(session, user_id):
            logger.info(f"Исп. беспл. услуга {service_id} user {user_id}")
            service_used = True
            await referral_service.award_referral_bonus_if_applicable(session, bot, user_id)
        else:
            logger.error(f"Ошибка отметки беспл. user {user_id}")
            await message.answer("Ошибка.", reply_markup=reply.get_main_menu(user_id))
            return

    if not service_used:
        return

    if not person_prefix:
        await crud.save_or_update_natal_data(
            session,
            user_id,
            f"{final_data['year']}-{final_data['month']:02d}-{final_data['day']:02d}",
            f"{final_data['hour']:02d}:{final_data['minute']:02d}",
            final_data['city'],
            final_data['latitude'],
            final_data['longitude'],
            final_data['timezone']
        )

    calc_error = False
    result = None
    try:
        if service_id == SERVICE_NATAL_CHART:
            result = await calculate_and_send_natal_chart(message, bot, final_data)
        elif service_id == SERVICE_FORECAST:
            result = await calculate_and_send_forecast(message, bot, final_data)
        elif service_id == SERVICE_COMPATIBILITY:
            result = await calculate_and_send_compatibility(message, bot, final_data)
        if result is None:
            calc_error = True
    except Exception as calc_e:
        logger.exception(f"Ошибка расчета {service_id} user {user_id}: {calc_e}")
        calc_error = True

    if calc_error:
        await message.answer(
            f"❌ Ошибка при расчете '{PAID_SERVICES[service_id]}'.",
            reply_markup=reply.get_main_menu(user_id)
        )
    else:
        await message.answer("✅ Запрос обработан.", reply_markup=reply.get_main_menu(user_id))
# --- Обработчики кнопок услуг ---
@astrology_router.message(F.text == "🔮 Натальная карта")
async def cmd_natal_chart(m: Message, state: FSMContext, session: AsyncSession):
    await start_astro_service(m, state, session, SERVICE_NATAL_CHART)

@astrology_router.message(F.text == "✨ Прогноз на год")
async def cmd_forecast(m: Message, state: FSMContext, session: AsyncSession):
    await start_astro_service(m, state, session, SERVICE_FORECAST)

@astrology_router.message(F.text == "💖 Совместимость")
async def cmd_compatibility(m: Message, state: FSMContext, session: AsyncSession):
    await start_astro_service(m, state, session, SERVICE_COMPATIBILITY)


# --- Обработчик подтверждения услуги ---
@astrology_router.callback_query(F.data.startswith("confirm_service:"))
async def handle_confirm_service(c: CallbackQuery, state: FSMContext, session: AsyncSession):
    sid = c.data.split(":", 1)[1]
    if sid not in [SERVICE_NATAL_CHART, SERVICE_FORECAST, SERVICE_COMPATIBILITY]:
        return

    uid = c.from_user.id
    can_use, _, is_free, _ = await user_service.check_service_availability(session, uid)

    if not can_use:
        await c.answer("Нет кредитов.", show_alert=True)
        try:
            await c.message.edit_text("Нет кредитов.", reply_markup=inline.get_payment_options_keyboard())
        except TelegramBadRequest:
            pass
        return

    await state.update_data(service_id=sid, is_free=is_free)
    await ask_for_year(c, state)
# --- Обработчики колбеков календаря и времени ---
@astrology_router.callback_query(NatalInput.waiting_for_year, F.data.startswith("natal_year:"))
@astrology_router.callback_query(NatalInput.waiting_for_partner_year, F.data.startswith("partner_natal_year:"))
async def cb_year(c: CallbackQuery, state: FSMContext):
    pre = "partner_" if c.data.startswith("partner_") else ""
    y = int(c.data.split(":")[-1])
    await process_year_input(c, state, y, pre)

@astrology_router.callback_query(NatalInput.waiting_for_month, F.data.startswith("natal_month:"))
@astrology_router.callback_query(NatalInput.waiting_for_partner_month, F.data.startswith("partner_natal_month:"))
async def cb_month(c: CallbackQuery, state: FSMContext):
    pre = "partner_" if c.data.startswith("partner_") else ""
    p = c.data.split(":")
    y, m = int(p[-2]), int(p[-1])
    await process_month_input(c, state, y, m, pre)

@astrology_router.callback_query(NatalInput.waiting_for_day, F.data.startswith("natal_day:"))
@astrology_router.callback_query(NatalInput.waiting_for_partner_day, F.data.startswith("partner_natal_day:"))
async def cb_day(c: CallbackQuery, state: FSMContext):
    pre = "partner_" if c.data.startswith("partner_") else ""
    p = c.data.split(":")
    y, m, d = int(p[-3]), int(p[-2]), int(p[-1])
    await process_day_input(c, state, y, m, d, pre)

@astrology_router.callback_query(NatalInput.waiting_for_hour, F.data.startswith("natal_hour:"))
@astrology_router.callback_query(NatalInput.waiting_for_partner_hour, F.data.startswith("partner_natal_hour:"))
async def cb_hour(c: CallbackQuery, state: FSMContext):
    pre = "partner_" if c.data.startswith("partner_") else ""
    p = c.data.split(":")
    y, m, d, h = int(p[-4]), int(p[-3]), int(p[-2]), int(p[-1])
    await process_hour_input(c, state, y, m, d, h, pre)

@astrology_router.callback_query(NatalInput.waiting_for_minute, F.data.startswith("natal_minute:"))
@astrology_router.callback_query(NatalInput.waiting_for_partner_minute, F.data.startswith("partner_natal_minute:"))
async def cb_minute(c: CallbackQuery, state: FSMContext):
    pre = "partner_" if c.data.startswith("partner_") else ""
    p = c.data.split(":")
    y, m, d, h, mi = int(p[-5]), int(p[-4]), int(p[-3]), int(p[-2]), int(p[-1])
    await process_minute_input(c, state, y, m, d, h, mi, pre)
# --- Обработчики возврата в календаре ---
@astrology_router.callback_query(StateFilter(NatalInput), F.data.endswith("_back_to_year"))
async def cb_back_to_year(c: CallbackQuery, state: FSMContext):
    pre = "partner_" if c.data.startswith("partner_") else ""
    await ask_for_year(c, state, pre)

@astrology_router.callback_query(StateFilter(NatalInput), F.data.contains("_back_to_month"))
async def cb_back_to_month(c: CallbackQuery, state: FSMContext):
    pre = "partner_" if c.data.startswith("partner_") else ""
    y = int(c.data.split(":")[-1])
    await state.update_data({f"{pre}year": y})
    markup = inline.create_calendar_months(y, f"{pre}natal")
    label = "П2: " if pre else ""
    text = f"📅 Год {label}{y}. Выберите {hbold('месяц')}:"
    try:
        await c.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    state_value = NatalInput.waiting_for_partner_month if pre else NatalInput.waiting_for_month
    await state.set_state(state_value)
    await c.answer()

@astrology_router.callback_query(StateFilter(NatalInput), F.data.contains("_back_to_day"))
async def cb_back_to_day(c: CallbackQuery, state: FSMContext):
    pre = "partner_" if c.data.startswith("partner_") else ""
    p = c.data.split(":")
    y, m = int(p[-2]), int(p[-1])
    await state.update_data({f"{pre}year": y, f"{pre}month": m})
    markup = inline.create_calendar_days(y, m, f"{pre}natal")
    label = "П2: " if pre else ""
    text = f"📅 Дата {label}{m:02d}.{y}. Выберите {hbold('день')}:"
    try:
        await c.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    state_value = NatalInput.waiting_for_partner_day if pre else NatalInput.waiting_for_day
    await state.set_state(state_value)
    await c.answer()

@astrology_router.callback_query(StateFilter(NatalInput), F.data.contains("_back_to_hour"))
async def cb_back_to_hour(c: CallbackQuery, state: FSMContext):
    pre = "partner_" if c.data.startswith("partner_") else ""
    p = c.data.split(":")
    y, m, d = int(p[-3]), int(p[-2]), int(p[-1])
    await state.update_data({f"{pre}year": y, f"{pre}month": m, f"{pre}day": d})
    markup = inline.create_time_hours(y, m, d, f"{pre}natal")
    label = "П2: " if pre else ""
    text = f"📅 Дата {label}{d:02d}.{m:02d}.{y}. Выберите {hbold('час')}:"
    try:
        await c.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    state_value = NatalInput.waiting_for_partner_hour if pre else NatalInput.waiting_for_hour
    await state.set_state(state_value)
    await c.answer()

# --- Обработчики ввода города ---
@astrology_router.message(NatalInput.waiting_for_city)
async def handle_city(m: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    await process_city_input(m, state, session, bot, "")

@astrology_router.message(NatalInput.waiting_for_partner_city)
async def handle_partner_city(m: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    await process_city_input(m, state, session, bot, "partner_")

# --- Функции расчета и отправки результатов (возвращают Optional[str]) ---
async def calculate_and_send_natal_chart(message: Message, bot: Bot, data: Dict[str, Any]) -> Optional[str]:
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "?"
    kr_instance = await get_kr_instance_from_data(data, user_name)
    if not kr_instance:
        await message.answer(f"Ошибка расчета данных. {ASTROLOGY_DISCLAIMER}")
        return None
    filename_base = f"natal_{user_id}_{int(datetime.now().timestamp())}"
    chart_path = await generate_natal_chart_image(kr_instance, filename_base)
    if chart_path and chart_path.exists():
        try:
            await message.answer_photo(FSInputFile(chart_path, filename=f"{filename_base}.png"), caption=f"🔮 Карта {hbold(user_name)}!", parse_mode="HTML")
        except Exception as e:
            logger.exception(f"Ошибка отправки фото {chart_path}: {e}")
            await message.answer("Ошибка отправки изображения.")
        finally:
            try:
                chart_path.unlink()
            except OSError as e_del:
                logger.error(f"Ошибка удаления файла {chart_path}: {e_del}")
    else:
        await message.answer("Не удалось создать изображение карты.")
    interpretation = await astrology_service.get_natal_chart_interpretation(kr_instance)
    await message.answer(interpretation, parse_mode="HTML", disable_web_page_preview=True)
    return interpretation

async def calculate_and_send_forecast(message: Message, bot: Bot, data: Dict[str, Any]) -> Optional[str]:
    kr_instance = await get_kr_instance_from_data(data, message.from_user.first_name or "?")
    if not kr_instance:
        await message.answer(f"Ошибка расчета данных. {ASTROLOGY_DISCLAIMER}")
        return None
    interpretation = await astrology_service.get_yearly_forecast_interpretation(kr_instance)
    await message.answer(interpretation, parse_mode="HTML", disable_web_page_preview=True)
    return interpretation

async def calculate_and_send_compatibility(message: Message, bot: Bot, data: Dict[str, Any]) -> Optional[str]:
    uname = message.from_user.first_name or "?"
    kr1 = await get_kr_instance_from_data(data, uname, "")
    kr2 = await get_kr_instance_from_data(data, uname, "partner_")
    if not kr1 or not kr2:
        await message.answer(f"Ошибка расчета данных партнеров. {ASTROLOGY_DISCLAIMER}")
        return None
    perc, interp = await astrology_service.get_compatibility_interpretation(kr1, kr2)
    res = f"📊 {hbold('Совместимость:')} {perc}%\n\n" if perc is not None else "📊 Оценка не определена.\n\n"
    res += interp
    await message.answer(res, parse_mode="HTML", disable_web_page_preview=True)
    return res
