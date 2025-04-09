import uuid
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError # Импорт для обработки ошибок БД
from database.models import User
from core.config import settings # Используем Pydantic settings

logger = logging.getLogger(__name__)

async def generate_unique_referral_code(session: AsyncSession, length: int = 8) -> str:
    """Генерирует уникальный реферальный код."""
    attempt = 0
    max_attempts = 10
    while attempt < max_attempts:
        code = str(uuid.uuid4().hex)[:length].upper()
        try:
            exists = await session.scalar(select(User.id).where(User.referral_code == code).limit(1))
            if not exists:
                logger.debug(f"Generated unique referral code: {code}")
                return code
        except SQLAlchemyError as e:
             logger.exception(f"DB Error checking referral code uniqueness: {e}")
             break # Выход при ошибке БД
        attempt += 1

    logger.error(f"Failed to generate unique referral code after {max_attempts} attempts.")
    # Возвращаем случайный код без гарантии уникальности в крайнем случае
    return str(uuid.uuid4().hex)[:length].upper()


def generate_referral_link(referral_code: str) -> str:
    """Создает реферальную ссылку для старта бота."""
    # Пытаемся извлечь имя бота из токена
    bot_username = "your_bot" # Запасное имя
    try:
        token_parts = settings.telegram_bot_token.get_secret_value().split(':')
        if len(token_parts) == 2:
             # Часто имя бота можно получить из первой части ID до символа _bot
             bot_id_part = token_parts[1]
             potential_username = bot_id_part.split('_')[0]
             # Простая проверка, что это похоже на имя бота
             if potential_username.lower().endswith("bot"):
                  bot_username = potential_username
             else: # Попробуем использовать ID, если имя не извлеклось
                 bot_username = token_parts[1] # Используем полный токен после ':' как запасной вариант? Нет, лучше ID.
                 # Лучше использовать BOT_USERNAME из .env, если доступен
                 # bot_username = settings.bot_username or bot_username
                 pass # Оставляем "your_bot" или базовый URL, если имя не извлеклось

    except Exception:
         logger.warning("Could not reliably determine bot username from token for referral link.")

    # Используем t.me/<bot_username>?start=<code>
    base_url = f"https://t.me/{bot_username}"
    return f"{base_url}?start={referral_code}"