import datetime
import calendar
import pytz # Добавлен pytz
import logging
from typing import Optional, Tuple, List # Добавлены List, Optional, Tuple
from babel.dates import format_date, get_month_names

logger = logging.getLogger(__name__)

# Получаем русские названия месяцев через Babel (делаем это один раз при загрузке модуля)
try:
    russian_months = get_month_names('wide', locale='ru_RU')
except Exception as e:
    logger.exception(f"Не удалось загрузить русские названия месяцев через Babel: {e}")
    # Запасной вариант
    russian_months = {1: "Янв", 2: "Фев", 3: "Мар", 4: "Апр", 5: "Май", 6: "Июн", 7: "Июл", 8: "Авг", 9: "Сен", 10: "Окт", 11: "Ноя", 12: "Дек"}


def get_russian_month_name(month_number: int) -> str:
    """Возвращает русское название месяца по его номеру (1-12)."""
    return russian_months.get(month_number, "Unknown") # Используем .get для безопасности

def get_days_in_month(year: int, month: int) -> int:
    """Возвращает количество дней в указанном месяце и годе."""
    try:
        # Проверяем корректность месяца перед вызовом monthrange
        if 1 <= month <= 12:
            return calendar.monthrange(year, month)[1]
        else:
            logger.warning(f"Неверный номер месяца: {month}")
            return 31 # Макс. значение по умолчанию
    except ValueError: # calendar.monthrange может выдать ValueError для невалидных годов
        logger.warning(f"Неверный год для get_days_in_month: {year}")
        return 31

def is_valid_date(year: int, month: int, day: int) -> bool:
    """Проверяет, является ли дата корректной."""
    if not (1 <= month <= 12): return False
    max_day = get_days_in_month(year, month)
    return 1 <= day <= max_day

def is_valid_time(hour: int, minute: int) -> bool:
    """Проверяет, является ли время корректным."""
    return 0 <= hour <= 23 and 0 <= minute <= 59

def format_datetime_for_kerykeion(year: int, month: int, day: int, hour: int, minute: int) -> Tuple[str, str]:
    """Форматирует дату и время для библиотеки Kerykeion."""
    # Дополнительная проверка валидности перед форматированием
    if not is_valid_date(year, month, day) or not is_valid_time(hour, minute):
        raise ValueError(f"Некорректная дата/время для форматирования: {year}-{month}-{day} {hour}:{minute}")
    date_str = f"{year:04d}-{month:02d}-{day:02d}" # Гарантируем 4 цифры для года
    time_str = f"{hour:02d}:{minute:02d}"
    return date_str, time_str

def get_current_utc_time_str() -> str:
    """Возвращает текущее время в UTC в формате HH:MM."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    return now_utc.strftime("%H:%M")

def parse_horoscope_time(time_str: str) -> Optional[datetime.time]:
    """Парсит время из строки HH:MM."""
    try:
        # Проверяем, что строка имеет правильный формат
        if len(time_str) == 5 and time_str[2] == ':':
            hour = int(time_str[:2])
            minute = int(time_str[3:])
            if is_valid_time(hour, minute):
                return datetime.time(hour, minute)
        logger.warning(f"Не удалось распознать время '{time_str}' (неверный формат).")
        return None
    except (ValueError, TypeError):
        logger.warning(f"Не удалось распознать время '{time_str}' (ошибка парсинга).")
        return None

def get_available_years(range_years: int = 100) -> List[int]:
    """Возвращает список доступных годов для выбора."""
    current_year = datetime.datetime.now().year
    # Добавим проверку на отрицательный диапазон
    if range_years < 0: range_years = 0
    # Возвращаем годы в порядке убывания
    return list(range(current_year, current_year - range_years - 1, -1))