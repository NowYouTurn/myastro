from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from core.config import settings

def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🔮 Натальная карта"), KeyboardButton(text="✨ Прогноз на год"))
    builder.row(KeyboardButton(text="💖 Совместимость"), KeyboardButton(text="🌙 Толкование сна"))
    builder.row(KeyboardButton(text="🍀 Приметы и Эзотерика"), KeyboardButton(text="✋ Хиромантия (Фото рук)"))
    builder.row(KeyboardButton(text="⏰ Ежедневный гороскоп"), KeyboardButton(text="💰 Баланс и Покупка"))
    builder.row(KeyboardButton(text="🎁 Реферальная программа"), KeyboardButton(text="ℹ️ Помощь"))
    if user_id in settings.admin_ids: builder.row(KeyboardButton(text="👑 Админ-панель"))
    return builder.as_markup(resize_keyboard=True)

def get_admin_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👤 Найти пользователя"))
    builder.row(KeyboardButton(text="💰 Управление кредитами"), KeyboardButton(text="📢 Сделать рассылку"))
    builder.row(KeyboardButton(text="📄 Логи бота/пользователя"), KeyboardButton(text="🔎 Проверить платеж ЮKassa"))
    # builder.row(KeyboardButton(text="⚙️ Статус сервисов")) # Пока не используется
    builder.row(KeyboardButton(text="⬅️ Назад в главное меню"))
    return builder.as_markup(resize_keyboard=True)

def get_confirmation_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder(); builder.row(KeyboardButton(text="✅ Да"), KeyboardButton(text="❌ Нет")); return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

def get_admin_confirm_credits_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder(); builder.row(KeyboardButton(text="✅ Подтвердить изменение"), KeyboardButton(text="❌ Отмена")); return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)