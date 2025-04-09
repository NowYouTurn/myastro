import logging
import sys
import asyncio # Добавлен импорт
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING, Optional, Any

# Используем Pydantic settings
from core.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from database.models import LogLevel, Log

# --- Database Log Handler ---
class DatabaseLogHandler(logging.Handler):
    """ Обработчик для записи логов в базу данных SQLAlchemy. """
    def __init__(self, session_factory: 'async_sessionmaker[AsyncSession]'):
        super().__init__()
        self.session_factory = session_factory
        self.setLevel(logging.DEBUG) # Уровень по умолчанию, фильтруем в логгере

    async def emit_async(self, record: logging.LogRecord):
        """ Асинхронная отправка записи в БД. """
        # Импортируем модели здесь, чтобы избежать циклов
        from database.models import Log, LogLevel

        log_level_name = record.levelname.upper()
        if log_level_name not in LogLevel.__members__: return # Не логируем неизвестные уровни в БД

        log_level = LogLevel[log_level_name]
        user_id = getattr(record, 'user_id', None)
        handler_name = getattr(record, 'handler_name', None)
        exc_text = None
        if record.exc_info: exc_text = logging.Formatter().formatException(record.exc_info)

        log_entry = Log(
            level=log_level, message=self.format(record), user_id=user_id,
            handler=handler_name, exception_info=exc_text
        )
        try:
            async with self.session_factory() as session:
                 # Используем begin_nested, чтобы ошибка записи лога не откатила основную транзакцию
                 async with session.begin_nested():
                      session.add(log_entry)
                 await session.commit() # Коммитим только запись лога
        except Exception as e:
            print(f"CRITICAL: Failed write log to DB: {e}", file=sys.stderr)
            print(f"Original Log Record: {record.__dict__}", file=sys.stderr)

    def emit(self, record: logging.LogRecord):
        """ Синхронный вызов для совместимости, запускает async задачу. """
        try:
            loop = asyncio.get_running_loop()
            # Используем call_soon_threadsafe, если emit вызывается из другого потока
            # loop.call_soon_threadsafe(asyncio.create_task, self.emit_async(record))
            # Если вызывается из того же потока asyncio:
            loop.create_task(self.emit_async(record))
        except RuntimeError: pass # Игнорируем, если нет запущенного цикла


# --- Настройка Логгера ---
def setup_logging(session_factory: Optional['async_sessionmaker[AsyncSession]'] = None):
    """ Настраивает систему логирования на основе Pydantic settings. """
    log_level_numeric = getattr(logging, settings.log_level, logging.INFO)
    formatter = logging.Formatter(settings.log_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level_numeric)
    for handler in root_logger.handlers[:]: root_logger.removeHandler(handler)

    # Консоль
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level_numeric)
    root_logger.addHandler(console_handler)

    # Файл
    if settings.log_file:
        try:
            file_handler = RotatingFileHandler(settings.log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.INFO) # В файл пишем INFO и выше
            root_logger.addHandler(file_handler)
        except Exception as e: root_logger.error(f"Failed setup file logger ({settings.log_file}): {e}")

    # БД
    db_logging_enabled = settings.log_to_db and session_factory
    if db_logging_enabled:
        db_handler = DatabaseLogHandler(session_factory)
        db_handler.setLevel(logging.INFO) # В БД пишем INFO и выше
        db_handler.setFormatter(formatter)
        root_logger.addHandler(db_handler)

    # Уровни логов библиотек
    logging.getLogger('aiogram').setLevel(logging.INFO)
    logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.INFO)
    logging.getLogger('httpx').setLevel(logging.INFO)
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger('kerykeion').setLevel(logging.INFO)
    logging.getLogger('PIL').setLevel(logging.INFO) # Уменьшаем болтливость Pillow
    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    logging.getLogger('geopy').setLevel(logging.INFO)
    logging.getLogger('asyncio').setLevel(logging.WARNING) # Уменьшаем болтливость asyncio

    root_logger.info(f"Logging setup complete. Level: {settings.log_level}. File: {settings.log_file}. DB Log: {db_logging_enabled}")