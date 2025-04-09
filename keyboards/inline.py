import calendar
import datetime
from typing import Optional, List, Dict, Tuple

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Используем Pydantic settings
from core.config import settings, PAID_SERVICES, PAYMENT_OPTIONS, SERVICE_COST, SERVICE_FORECAST

from utils.date_time_helpers import get_russian_month_name, get_days_in_month, get_available_years

# --- Клавиатуры для ввода даты и времени ---
def create_calendar_years(years: List[int], callback_prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); [builder.button(text=str(y), callback_data=f"{callback_prefix}_year:{y}") for y in years]; builder.adjust(4); return builder.as_markup()
def create_calendar_months(year: int, callback_prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); [builder.button(text=get_russian_month_name(m), callback_data=f"{callback_prefix}_month:{year}:{m}") for m in range(1, 13)]; builder.button(text="⬅️ Год", callback_data=f"{callback_prefix}_back_to_year"); builder.adjust(3); return builder.as_markup()
def create_calendar_days(year: int, month: int, callback_prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); [builder.button(text=str(d), callback_data=f"{callback_prefix}_day:{year}:{month}:{d}") for d in range(1, get_days_in_month(year, month) + 1)]; builder.button(text="⬅️ Месяц", callback_data=f"{callback_prefix}_back_to_month:{year}"); builder.adjust(7); return builder.as_markup()
def create_time_hours(year: int, month: int, day: int, callback_prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); [builder.button(text=f"{h:02d}", callback_data=f"{callback_prefix}_hour:{year}:{month}:{day}:{h}") for h in range(24)]; builder.button(text="⬅️ День", callback_data=f"{callback_prefix}_back_to_day:{year}:{month}"); builder.adjust(6); return builder.as_markup()
def create_time_minutes(year: int, month: int, day: int, hour: int, callback_prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); [builder.button(text=f"{m:02d}", callback_data=f"{callback_prefix}_minute:{year}:{month}:{day}:{hour}:{m}") for m in range(0, 60, 5)]; builder.button(text="⬅️ Час", callback_data=f"{callback_prefix}_back_to_hour:{year}:{month}:{day}"); builder.adjust(6); return builder.as_markup()

# --- Клавиатура для выбора времени ежедневного гороскопа ---
def create_horoscope_time_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); [builder.button(text=f"{h:02d}:00", callback_data=f"set_horo_time:{h:02d}:00") for h in range(24)]; builder.button(text="❌ Отключить гороскоп", callback_data="set_horo_time:disable"); builder.adjust(4); return builder.as_markup()

# --- Клавиатура для принятия условий ---
def get_accept_terms_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); builder.button(text="✅ Принять условия", callback_data="accept_terms"); return builder.as_markup()

# --- Клавиатура для подтверждения списания кредитов ---
def get_confirm_service_keyboard(service_id: str, credits_needed: int, current_credits: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if current_credits >= credits_needed or credits_needed == 0:
        cost = f"{credits_needed} кр." if credits_needed != 0 else "бесплатно"
        remain = current_credits - credits_needed if credits_needed > 0 else current_credits
        builder.button(text=f"✅ Использовать ({cost}, останется {remain})", callback_data=f"confirm_service:{service_id}")
    else: builder.button(text=f"Недостаточно кредитов ({current_credits}/{credits_needed})", callback_data="dummy_nocredits")
    pdf_path = settings.pdf_dir / f"{service_id}_example.pdf"
    if pdf_path.exists(): builder.button(text="📄 Посмотреть пример", callback_data=f"show_pdf_example:{service_id}")
    builder.button(text="💰 Купить кредиты", callback_data="buy_credits_menu"); builder.button(text="❌ Отмена", callback_data="cancel_service"); builder.adjust(1); return builder.as_markup()

# --- Клавиатура для выбора опции покупки кредитов ---
def get_payment_options_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); [builder.button(text=f"{d['description']} за {d['price']/100:.0f} ₽", callback_data=f"create_payment:{k}") for k, d in settings.PAYMENT_OPTIONS.items()]; builder.button(text="❌ Отмена", callback_data="cancel_payment"); builder.adjust(1); return builder.as_markup()

# --- Клавиатура со ссылкой на оплату (БЕЗ кнопки проверки) ---
def get_payment_link_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); builder.button(text="➡️ Перейти к оплате (ЮKassa)", url=payment_url); builder.button(text="❌ Отмена", callback_data="cancel_payment"); builder.adjust(1); return builder.as_markup()

# --- Клавиатура для хиромантии ---
def get_palm_hand_selection_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); builder.button(text="Левая рука", callback_data="palm_hand:left"); builder.button(text="Правая рука", callback_data="palm_hand:right"); builder.button(text="❌ Отмена", callback_data="cancel_palmistry"); builder.adjust(2); return builder.as_markup()

# --- Клавиатура отмены FSM ---
def get_cancel_keyboard(callback_data="fsm_cancel") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder(); builder.button(text="❌ Отмена", callback_data=callback_data); return builder.as_markup()