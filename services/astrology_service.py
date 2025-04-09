import logging
import asyncio
from typing import Optional, Tuple, Dict, Any
from kerykeion import AstrologicalSubject as KrInstance
from kerykeion import AstrologicalSubject as MakeSvgInstance
from kerykeion.utilities import setup_logging as setup_config
from kerykeion import KerykeionChartSVG as get_chart_options_by_name
from pathlib import Path
import datetime
import pytz
from aiogram.types import FSInputFile
from datetime import datetime

from database.models import KrInstance  # Убедись, что путь корректен

logger = logging.getLogger(__name__)

# Используем Pydantic settings
from core.config import settings

# Импорт моделей и сервисов
from database.models import NatalData
from services.openai_service import get_openai_interpretation

logger = logging.getLogger(__name__)

async def get_natal_data_kerykeion(
    first_name: str, birth_date: str, birth_time: str, city_name: str,
    latitude: float, longitude: float, timezone_str: str
) -> Optional[KrInstance]:
    """ Создает объект KrInstance с натальными данными. """
    try:
        year, month, day = map(int, birth_date.split('-'))
        hour, minute = map(int, birth_time.split(':'))
        # Проверка валидности даты/времени
        datetime.datetime(year, month, day, hour, minute)
        # Проверка и исправление таймзоны
        try: pytz.timezone(timezone_str)
        except pytz.exceptions.UnknownTimeZoneError: timezone_str = "UTC"; logger.warning(f"Неизвестная TZ '{timezone_str}', используем UTC.")

        # Настройка папки Kerykeion перед вызовом
        await asyncio.to_thread(setup_config, settings.temp_dir)

        kr_instance = await asyncio.to_thread(
            KrInstance, name=first_name, year=year, month=month, day=day,
            hour=hour, minute=minute, city=city_name,
            lat=latitude, lng=longitude, tz_str=timezone_str )
        logger.info(f"KrInstance создан для {first_name}")
        return kr_instance
    except ValueError as ve: logger.error(f"Некорректные дата/время для Kerykeion ({first_name}): {ve}"); return None
    except Exception as e: logger.exception(f"Ошибка KrInstance для {first_name}: {e}"); return None


# TODO: Профилировать эту функцию при необходимости
async def generate_natal_chart_image(kr_instance: KrInstance, filename_base: str) -> Optional[Path]:
    """ Генерирует SVG натальной карты и конвертирует в PNG. """
    if not kr_instance: return None
    svg_path = settings.temp_dir / f"{filename_base}.svg"
    png_path = settings.temp_dir / f"{filename_base}.png"
    final_svg_path = None # Путь к реально созданному SVG

    try:
        chart_options = get_chart_options_by_name('astrolog') or {}

        def create_svg_sync():
            setup_config(settings.temp_dir)
            instance_name = kr_instance.name
            svg_maker = MakeSvgInstance(kr_instance, chart_type="Natal", chart_options=chart_options)
            svg_maker.makeSVG()
            # Kerykeion создает файл <name>_natal.svg
            return settings.temp_dir / f"{instance_name}_natal.svg"

        expected_svg_path = await asyncio.to_thread(create_svg_sync)

        if not expected_svg_path.exists():
             logger.error(f"Kerykeion не создал SVG: {expected_svg_path}")
             # Пробуем найти по нашему имени файла
             if svg_path.exists(): final_svg_path = svg_path; logger.info(f"Найден SVG по альтернативному пути: {svg_path}")
             else: logger.error(f"SVG файл не найден."); return None
        else:
              if expected_svg_path != svg_path:
                   try: expected_svg_path.rename(svg_path); final_svg_path = svg_path; logger.debug(f"SVG переименован в {svg_path}")
                   except OSError as rename_err: logger.warning(f"Не удалось переименовать {expected_svg_path} в {svg_path}: {rename_err}. Используем {expected_svg_path}"); final_svg_path = expected_svg_path
              else: final_svg_path = svg_path

        logger.info(f"SVG натальная карта создана: {final_svg_path}")

        # Конвертация SVG в PNG
        try:
            import cairosvg
            await asyncio.to_thread(cairosvg.svg2png, url=str(final_svg_path), write_to=str(png_path), dpi=150)
            logger.info(f"PNG натальная карта создана: {png_path}")
            return png_path
        except ImportError: logger.error("CairoSVG не найден. pip install cairosvg"); return None
        except Exception as convert_err: logger.exception(f"Ошибка конвертации SVG в PNG: {convert_err}"); return None
        finally: # Удаляем SVG в любом случае после попытки конвертации
             if final_svg_path and final_svg_path.exists():
                 try: final_svg_path.unlink(); logger.debug(f"Временный SVG удален: {final_svg_path}")
                 except OSError as del_err: logger.error(f"Не удалось удалить SVG {final_svg_path}: {del_err}")

    except Exception as e: logger.exception(f"Ошибка генерации изображения карты: {e}"); return None


def get_relevant_astro_data(kr_instance: KrInstance) -> Dict[str, Any]:
    """ Извлекает ключевые астрологические данные из KrInstance для передачи в OpenAI. """
    if not kr_instance: return {}
    # Используем .get() для домов
    data = {
        "name": kr_instance.name or "Человек",
        "sun": {"sign": kr_instance.sun['sign'], "pos": kr_instance.sun['position'], "house": kr_instance.sun.get('house', 'N/A')},
        "moon": {"sign": kr_instance.moon['sign'], "pos": kr_instance.moon['position'], "house": kr_instance.moon.get('house', 'N/A')},
        "mercury": {"sign": kr_instance.mercury['sign'], "pos": kr_instance.mercury['position'], "house": kr_instance.mercury.get('house', 'N/A')},
        "venus": {"sign": kr_instance.venus['sign'], "pos": kr_instance.venus['position'], "house": kr_instance.venus.get('house', 'N/A')},
        "mars": {"sign": kr_instance.mars['sign'], "pos": kr_instance.mars['position'], "house": kr_instance.mars.get('house', 'N/A')},
        "jupiter": {"sign": kr_instance.jupiter['sign'], "pos": kr_instance.jupiter['position'], "house": kr_instance.jupiter.get('house', 'N/A')},
        "saturn": {"sign": kr_instance.saturn['sign'], "pos": kr_instance.saturn['position'], "house": kr_instance.saturn.get('house', 'N/A')},
        "asc": {"sign": kr_instance.first_house['sign'], "pos": kr_instance.first_house['position']},
        "mc": {"sign": kr_instance.tenth_house['sign'], "pos": kr_instance.tenth_house['position']},
    }
    # Преобразуем в плоский словарь для format()
    flat_data = {f"{k}_{subk}": v2 for k, v1 in data.items() if isinstance(v1, dict) for subk, v2 in v1.items()}
    flat_data["name"] = data["name"]
    flat_data["disclaimer"] = settings.ASTROLOGY_DISCLAIMER # Добавляем дисклеймер
    return flat_data


async def get_natal_chart_interpretation(kr_instance: KrInstance) -> str:
    if not kr_instance: return "Ошибка: Нет данных карты."
    prompt_data = get_relevant_astro_data(kr_instance)
    if not prompt_data: return "Ошибка: Не удалось извлечь данные для ИИ."
    return await get_openai_interpretation("natal_chart", prompt_data, context="natal")


async def get_yearly_forecast_interpretation(kr_instance: KrInstance) -> str:
    if not kr_instance: return "Ошибка: Нет данных карты."
    prompt_data = get_relevant_astro_data(kr_instance)
    if not prompt_data: return "Ошибка: Не удалось извлечь данные для ИИ."
    current_year = datetime.datetime.now().year
    prompt_data["start_year"] = current_year; prompt_data["end_year"] = current_year + 1
    return await get_openai_interpretation("yearly_forecast", prompt_data, context="forecast")


async def get_compatibility_interpretation(kr1: KrInstance, kr2: KrInstance) -> Tuple[Optional[int], str]:
    if not kr1 or not kr2: return None, "Ошибка: Нет данных одного из партнеров."
    data1 = get_relevant_astro_data(kr1); data2 = get_relevant_astro_data(kr2)
    if not data1 or not data2: return None, "Ошибка: Не удалось извлечь данные для ИИ."

    prompt_data = {
        "name1": data1.get("name", "Партнер 1"), "name2": data2.get("name", "Партнер 2"),
        "sun1_sign": data1.get("sun_sign"), "moon1_sign": data1.get("moon_sign"),
        "venus1_sign": data1.get("venus_sign"), "mars1_sign": data1.get("mars_sign"),
        "asc1_sign": data1.get("asc_sign"),
        "sun2_sign": data2.get("sun_sign"), "moon2_sign": data2.get("moon_sign"),
        "venus2_sign": data2.get("venus_sign"), "mars2_sign": data2.get("mars_sign"),
        "asc2_sign": data2.get("asc_sign"),
        "disclaimer": settings.ASTROLOGY_DISCLAIMER
    }
    prompt_data = {k: v if v is not None else "N/A" for k, v in prompt_data.items()} # Заменяем None

    full_interpretation = await get_openai_interpretation("compatibility", prompt_data, context="compatibility")

    percentage = None; import re
    match = re.match(r"\[(\d{1,3})%\]", full_interpretation)
    if match:
        try: percentage = int(match.group(1)); text_interpretation = re.sub(r"\[\d{1,3}%\]\s*", "", full_interpretation, count=1).strip()
        except (ValueError, IndexError): text_interpretation = full_interpretation.strip()
    else: text_interpretation = full_interpretation.strip(); logger.warning(f"Не найден процент совместимости для {data1.get('name')}/{data2.get('name')}")

    return percentage, text_interpretation


async def get_daily_horoscope_interpretation(kr_instance: KrInstance) -> str:
    if not kr_instance: return "Ошибка: Нет данных карты."
    astro_data = get_relevant_astro_data(kr_instance)
    if not astro_data: return "Ошибка: Не удалось извлечь данные для ИИ."

    user_tz_str = kr_instance.tz_str or "UTC"
    try: user_tz = pytz.timezone(user_tz_str)
    except pytz.exceptions.UnknownTimeZoneError: user_tz = pytz.utc
    today_date_str = datetime.datetime.now(user_tz).strftime('%d %B %Y') # Используем Babel по умолчанию

    prompt_data = {
        "name": astro_data.get("name", "Вас"), "today_date": today_date_str,
        "sun_sign": astro_data.get("sun_sign", "N/A"), "moon_sign": astro_data.get("moon_sign", "N/A"),
        "asc_sign": astro_data.get("asc_sign", "N/A")
    }
    return await get_openai_interpretation("daily_horoscope", prompt_data, context="daily_horoscope", timeout_seconds=60)

async def get_kr_instance_from_data(data: Dict[str, Any], name: str, prefix: str = "") -> Optional[KrInstance]:
    try:
        dt_str = f"{data[f'{prefix}year']}-{data[f'{prefix}month']:02d}-{data[f'{prefix}day']:02d} {data[f'{prefix}hour']:02d}:{data[f'{prefix}minute']:02d}"
        dt_obj = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        return KrInstance(
            name=name,
            datetime_utc=dt_obj,
            city=data[f"{prefix}city"],
            latitude=data[f"{prefix}latitude"],
            longitude=data[f"{prefix}longitude"],
            timezone=data[f"{prefix}timezone"]
        )
    except Exception as e:
        logger.exception(f"Ошибка создания KrInstance: {e}")
        return None