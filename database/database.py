import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

# Используем Pydantic settings
from core.config import settings

logger = logging.getLogger(__name__)

DATABASE_URL = settings.database_url # Получаем URL из настроек

try:
    engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
    async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    logger.info(f"Подключение к БД настроено: {DATABASE_URL}")

except Exception as e:
    logger.exception(f"Ошибка подключения к БД {DATABASE_URL}: {e}")
    raise

# Базовый класс для декларативных моделей SQLAlchemy
Base = declarative_base()

async def init_models():
    """
    Проверяет соединение с БД. Создание таблиц выполняется через Alembic.
    """
    logger.info("Проверка соединения с БД... (Таблицы создаются через 'alembic upgrade head')")
    try:
        async with engine.connect() as conn:
            if engine.dialect.name == "sqlite":
                 await conn.execute(text("PRAGMA foreign_keys=ON"))
            logger.info("Проверка соединения с БД прошла успешно.")
    except Exception as e:
         logger.exception(f"Не удалось подключиться к БД при проверке в init_models: {e}")
         raise