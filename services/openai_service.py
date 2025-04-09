import logging
import asyncio
import base64
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
import aiofiles
import json # Добавлен json

from openai import (
    AsyncOpenAI, OpenAIError, RateLimitError, APIError, Timeout, BadRequestError, AuthenticationError, PermissionDeniedError
)
# Используем Pydantic settings
from core.config import settings

logger = logging.getLogger(__name__)

# --- Загрузка промптов ---
async def load_prompt(filename: str) -> str:
    filepath = settings.prompt_dir / filename
    try:
        async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f: return await f.read()
    except FileNotFoundError: logger.error(f"Файл промпта не найден: {filepath}"); return "Ошибка: Не найден шаблон запроса."
    except Exception as e: logger.exception(f"Ошибка чтения файла промпта {filepath}: {e}"); return "Ошибка: Не прочитан шаблон запроса."

# Загружаем системный промпт в фоне при старте
# common_system_prompt_task = asyncio.create_task(load_prompt("common_system.txt"))
# Лучше загружать его при первом вызове или передавать явно
_common_system_prompt = None
async def get_system_prompt() -> str:
     global _common_system_prompt
     if _common_system_prompt is None:
          _common_system_prompt = await load_prompt("common_system.txt")
     return _common_system_prompt

# --- Клиент OpenAI ---
client: Optional[AsyncOpenAI] = None
if settings.openai_api_key:
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), timeout=settings.openai_timeout)
        logger.info(f"Клиент OpenAI инициализирован ({settings.openai_model}).")
    except Exception as e: logger.exception(f"Ошибка инициализации клиента OpenAI: {e}")
else: logger.error("OpenAI API Key не найден.")


async def get_openai_interpretation(
    prompt_template_name: str, prompt_data: Dict[str, Any], context: str = "general",
    temperature: float = 0.7, max_tokens: int = 1000, timeout_seconds: Optional[int] = None
) -> str:
    if not client: return "Ошибка: Клиент OpenAI не инициализирован."

    user_prompt_template = await load_prompt(f"{prompt_template_name}.txt")
    if user_prompt_template.startswith("Ошибка:"): return user_prompt_template
    try: user_prompt = user_prompt_template.format(**prompt_data)
    except KeyError as e: logger.error(f"Нет ключа '{e}' для шаблона {prompt_template_name}"); return "Ошибка: Недостаточно данных для запроса."
    except Exception as e: logger.exception(f"Ошибка форматирования {prompt_template_name}: {e}"); return "Ошибка: Не удалось сформировать запрос."

    system_prompt = await get_system_prompt()
    request_timeout = timeout_seconds if timeout_seconds is not None else settings.openai_timeout

    logger.info(f"Запрос OpenAI ({context}). Model: {settings.openai_model}. Timeout: {request_timeout}s.")
    logger.debug(f"System: {system_prompt[:100]}... User: {user_prompt[:100]}...")
    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=temperature, max_tokens=max_tokens, timeout=request_timeout,
        )
        interpretation = response.choices[0].message.content.strip()
        logger.info(f"Ответ OpenAI ({context}) {len(interpretation)} chars.")
        if not interpretation: logger.warning(f"OpenAI ({context}) пустой ответ."); return "ИИ не смог предоставить ответ."
        return interpretation
    except Timeout: logger.error(f"Тайм-аут {request_timeout}s OpenAI ({context})."); return f"Ошибка: Превышено время ожидания ИИ ({request_timeout} сек)."
    except RateLimitError: logger.error(f"Лимит запросов OpenAI ({context})."); return "Ошибка: Слишком много запросов к ИИ. Подождите."
    except AuthenticationError: logger.error(f"Ошибка аутентификации OpenAI."); return "Ошибка: Неверный ключ OpenAI API."
    except PermissionDeniedError: logger.error(f"Отказано в доступе OpenAI."); return "Ошибка: Нет доступа к модели OpenAI."
    except BadRequestError as e: logger.exception(f"Ошибка запроса OpenAI ({context}): {e}"); return f"Ошибка: Некорректный запрос к ИИ (BadRequest: {getattr(e, 'code', 'N/A')})."
    except APIError as e: logger.exception(f"Ошибка API OpenAI ({context}): {e}"); return f"Ошибка: Сервис ИИ недоступен (API Error: {e.status_code})."
    except OpenAIError as e: logger.exception(f"Общая ошибка OpenAI ({context}): {e}"); return f"Ошибка: Внутренняя ошибка ИИ ({type(e).__name__})."
    except Exception as e: logger.exception(f"Непредвиденная ошибка OpenAI ({context}): {e}"); return "Ошибка: Непредвиденная ошибка при обращении к ИИ."


async def get_dream_interpretation(dream_text: str) -> str:
    prompt_data = {"dream_text": dream_text}
    return await get_openai_interpretation("dream_interpretation", prompt_data, context="dream")

async def get_sign_interpretation(sign_text: str) -> str:
    prompt_data = {"sign_text": sign_text}
    return await get_openai_interpretation("sign_interpretation", prompt_data, context="signs")

async def get_palmistry_analysis(image_data_left: bytes, image_data_right: bytes) -> str:
    if not client: return "Ошибка: Клиент OpenAI не инициализирован."
    if "vision" not in settings.openai_model.lower() and "o" not in settings.openai_model.lower():
         logger.warning(f"Модель {settings.openai_model} может не поддерживать Vision.")

    logger.info(f"Запрос OpenAI Vision (palmistry). Модель: {settings.openai_model}.")
    base64_image_left = base64.b64encode(image_data_left).decode('utf-8')
    base64_image_right = base64.b64encode(image_data_right).decode('utf-8')

    palmistry_prompt_template = await load_prompt("palmistry_analysis.txt")
    if palmistry_prompt_template.startswith("Ошибка:"): return palmistry_prompt_template
    try: user_prompt_text = palmistry_prompt_template.format(disclaimer=settings.PALMISTRY_DISCLAIMER)
    except Exception as e: logger.exception(f"Ошибка форматирования palmistry_analysis: {e}"); return "Ошибка формирования запроса (хиромантия)."

    system_prompt = await get_system_prompt()
    request_timeout = settings.openai_timeout + 60 # Больше времени для Vision

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt + "\nТы также выполняешь базовый визуальный анализ ладоней."},
                {"role": "user", "content": [
                        {"type": "text", "text": user_prompt_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image_left}", "detail": "low"}},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image_right}", "detail": "low"}} ] }
            ], max_tokens=1500, timeout=request_timeout
        )
        analysis = response.choices[0].message.content.strip()
        logger.info(f"Ответ OpenAI Vision (palmistry) {len(analysis)} chars.")
        if not analysis: logger.warning("OpenAI Vision (palmistry) пустой ответ."); return f"ИИ не смог предоставить анализ. {settings.PALMISTRY_DISCLAIMER}"
        if settings.PALMISTRY_DISCLAIMER not in analysis: analysis += "\n\n" + settings.PALMISTRY_DISCLAIMER # Добавляем дисклеймер, если его нет
        return analysis
    except Timeout: logger.error(f"Тайм-аут {request_timeout}s OpenAI Vision."); return f"Ошибка: Превышено время ожидания ИИ. {settings.PALMISTRY_DISCLAIMER}"
    except RateLimitError: logger.error("Лимит запросов OpenAI (palmistry)."); return f"Ошибка: Слишком много запросов к ИИ. {settings.PALMISTRY_DISCLAIMER}"
    except AuthenticationError: logger.error(f"Ошибка аутентификации OpenAI."); return f"Ошибка: Неверный ключ OpenAI API. {settings.PALMISTRY_DISCLAIMER}"
    except PermissionDeniedError: logger.error(f"Отказано в доступе OpenAI."); return f"Ошибка: Нет доступа к модели OpenAI. {settings.PALMISTRY_DISCLAIMER}"
    except BadRequestError as e:
         logger.exception(f"Ошибка запроса OpenAI Vision: {e}")
         is_image_error = False; error_detail = ""
         if isinstance(e.body, dict) and 'error' in e.body: error_detail = str(e.body['error'].get('message', '')).lower()
         if 'image' in error_detail or 'invalid_url' in error_detail or 'download' in error_detail or getattr(e, 'code', '') in ['invalid_image_url', 'invalid_request']: is_image_error = True
         if is_image_error: return f"Ошибка: Не удалось обработать фото. Убедитесь, что это четкие фото ладоней (JPG/PNG). {settings.PALMISTRY_DISCLAIMER}"
         else: return f"Ошибка: Некорректный запрос к ИИ (BadRequest: {getattr(e, 'code', 'N/A')}). {settings.PALMISTRY_DISCLAIMER}"
    except APIError as e: logger.exception(f"Ошибка API OpenAI Vision: {e}"); return f"Ошибка: Сервис ИИ недоступен (API Error: {e.status_code}). {settings.PALMISTRY_DISCLAIMER}"
    except OpenAIError as e: logger.exception(f"Общая ошибка OpenAI Vision: {e}"); return f"Ошибка: Внутренняя ошибка ИИ ({type(e).__name__}). {settings.PALMISTRY_DISCLAIMER}"
    except Exception as e: logger.exception(f"Непредвиденная ошибка OpenAI Vision: {e}"); return f"Ошибка: Непредвиденная ошибка при обращении к ИИ. {settings.PALMISTRY_DISCLAIMER}"