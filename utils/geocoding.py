import logging
import asyncio # Добавлен asyncio
from typing import Optional, Tuple
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import (
    GeocoderTimedOut, GeocoderServiceError, GeocoderAuthenticationFailure,
    GeocoderInsufficientPrivileges, GeocoderParseError, GeocoderQueryError, GeocoderUnavailable
)
import pytz
import datetime # Не используется здесь напрямую, но может пригодиться для TimezoneFinder

logger = logging.getLogger(__name__)

# Инициализация геокодера
geolocator = Nominatim(user_agent="astro_telegram_bot/1.0 (contact: ваш_контакт_или_ссылка)")
# RateLimiter для Nominatim (1 запрос в секунду)
geocode_sync = RateLimiter(geolocator.geocode, min_delay_seconds=1.1, return_value_on_exception=None) # Увеличили задержку

# Асинхронная обертка для geocode_sync
async def geocode(city_name: str, **kwargs) -> Optional[any]: # Используем Any для location
     return await asyncio.to_thread(geocode_sync, city_name, **kwargs)

# --- Определение Timezone ---
_timezone_finder = None
def get_timezone_finder():
     """ Ленивая инициализация TimezoneFinder. """
     global _timezone_finder
     if _timezone_finder is None:
          try:
               from timezonefinder import TimezoneFinder
               _timezone_finder = TimezoneFinder()
               logger.info("TimezoneFinder инициализирован.")
          except ImportError:
               logger.warning("timezonefinder не установлен. pip install timezonefinder[numba]")
               _timezone_finder = False # Флаг, что библиотека недоступна
     return _timezone_finder

def get_timezone_at(lat: float, lng: float) -> Optional[str]:
     """ Получает таймзону по координатам (синхронная). """
     tf = get_timezone_finder()
     if tf: # Если tf не False (т.е. импортирован)
          try:
               return tf.timezone_at(lng=lng, lat=lat)
          except Exception as e:
               logger.exception(f"Ошибка TimezoneFinder для {lat}, {lng}: {e}")
     return None

# --- Основная функция ---
async def get_coordinates_and_timezone(city_name: str) -> Optional[Tuple[float, float, str]]:
    """
    Асинхронно получает координаты (широта, долгота) и часовой пояс для города.
    Использует Geopy (Nominatim) и TimezoneFinder.
    """
    location = None
    try:
        logger.info(f"Запрос координат для: {city_name}")
        # Используем асинхронную обертку geocode
        location = await geocode(city_name, language='ru', timeout=10)

        if location:
            latitude, longitude = location.latitude, location.longitude
            logger.info(f"Найдены координаты для '{city_name}': {latitude=}, {longitude=}")

            # Получаем таймзону (запускаем синхронную функцию в потоке)
            timezone_str = await asyncio.to_thread(get_timezone_at, latitude, longitude)

            if timezone_str:
                # Проверка валидности таймзоны
                try:
                     pytz.timezone(timezone_str); logger.info(f"Таймзона для '{city_name}': {timezone_str}")
                     return latitude, longitude, timezone_str
                except pytz.exceptions.UnknownTimeZoneError:
                     logger.warning(f"Невалидный TZ '{timezone_str}' для '{city_name}'. Используем UTC.")
                     return latitude, longitude, "UTC"
            else:
                logger.warning(f"Не удалось определить TZ для '{city_name}' ({latitude}, {longitude}). Используем UTC.")
                return latitude, longitude, "UTC"
        else:
            logger.warning(f"Город '{city_name}' не найден геокодером.")
            return None

    except GeocoderTimedOut: logger.error(f"Тайм-аут геокодера для '{city_name}'"); return None
    except GeocoderServiceError as e: logger.error(f"Ошибка сервиса геокодера для '{city_name}': {e}"); return None
    except GeocoderQueryError as e: logger.warning(f"Некорректный запрос геокодера для '{city_name}': {e}"); return None
    except GeocoderUnavailable as e: logger.error(f"Сервис геокодера недоступен для '{city_name}': {e}"); return None
    except Exception as e: logger.exception(f"Непредвиденная ошибка геокодирования '{city_name}': {e}"); return None