import logging
from typing import Callable, Dict, Any, Awaitable, Optional
from aiogram import BaseMiddleware
from aiogram.types import Update, User as AiogramUser

# Фильтр для добавления атрибутов по умолчанию
class ContextFilter(logging.Filter):
    def filter(self, record):
        record.user_id = getattr(record, 'user_id', 'N/A')
        record.handler_name = getattr(record, 'handler_name', 'N/A')
        return True
logging.getLogger().addFilter(ContextFilter()) # Применяем глобально

class LoggingContextMiddleware(BaseMiddleware):
    """ Добавляет user_id и handler_name в LogRecord для формата лога. """
    async def __call__(self, handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]], event: Update, data: Dict[str, Any]) -> Any:
        user: Optional[AiogramUser] = data.get('event_from_user')
        user_id = user.id if user else None
        handler_obj = data.get('handler')
        handler_name = 'unknown'
        if handler_obj: # Пытаемся получить имя функции хендлера
             callback = getattr(handler_obj, 'callback', None)
             if callback and hasattr(callback, '__name__'): handler_name = callback.__name__
             # Добавить другие способы получения имени, если нужно (для Router и т.д.)

        # Создаем LoggerAdapter для передачи доп. данных в форматтер
        logger = logging.getLogger() # Получаем корневой логгер
        extra_data = {'user_id': user_id or 'N/A', 'handler_name': handler_name or 'N/A'}
        adapter = logging.LoggerAdapter(logger, extra_data)
        # Или используем Filters, как в предыдущей версии (менее предпочтительно)

        # Для простоты и совместимости с текущим форматом, установим атрибуты напрямую
        # Это сработает, т.к. фильтр ContextFilter уже применен
        log_record_factory = logging.getLogRecordFactory()
        def record_factory_with_context(*args, **kwargs):
             record = log_record_factory(*args, **kwargs)
             record.user_id = user_id or 'N/A'
             record.handler_name = handler_name or 'N/A'
             return record
        original_factory = logging.getLogRecordFactory()
        logging.setLogRecordFactory(record_factory_with_context)

        try: return await handler(event, data)
        finally: logging.setLogRecordFactory(original_factory) # Восстанавливаем фабрику