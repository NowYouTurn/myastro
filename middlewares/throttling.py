import time
import logging
from typing import Callable, Optional, Dict, Any, Awaitable, Union # Добавлен Union

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
# Используем встроенный storage из dispatcher или MemoryStorage для простоты
from aiogram.fsm.storage.base import BaseStorage, StorageKey
# Или from aiogram.fsm.storage.memory import MemoryStorage

# Импортируем настройки
from core.config import settings

logger = logging.getLogger(__name__)

# throttle_storage = MemoryStorage() # Убрали глобальный MemoryStorage

class ThrottlingMiddleware(BaseMiddleware):
    """ Middleware для ограничения частоты запросов от пользователя. """
    def __init__(self,
                 rate_limit: float = settings.throttling_rate_limit,
                 rate_period: float = settings.throttling_rate_period,
                 storage: Optional[BaseStorage] = None): # Принимаем storage из dispatcher
        super().__init__()
        self.rate_limit = rate_limit
        self.rate_period = rate_period # Не используется в этой реализации
        # self.storage = storage or MemoryStorage() # Используем переданный или MemoryStorage
        # В Aiogram 3 storage доступен через data['state'].storage
        # logger.info(f"Throttling enabled: limit={self.rate_limit}s")

    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], Dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: Dict[str, Any]
    ) -> Any:
        user = data.get('event_from_user')
        state: Optional[FSMContext] = data.get('state') # Получаем state из data

        if not user or not state: # Если нет пользователя или state, пропускаем
            return await handler(event, data)

        user_id = user.id
        current_time = time.time()

        # Используем storage из FSMContext
        storage: BaseStorage = state.storage
        # Формируем ключ для хранения времени
        # Используем StorageKey для корректной работы с разными storage
        bot_id = data['bot'].id # Получаем bot_id
        chat_id = event.chat.id if isinstance(event, Message) else event.message.chat.id # Получаем chat_id
        key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id, key="throttle")

        # Получаем данные из стораджа
        throttle_data = await storage.get_data(key=key)
        last_time = throttle_data.get("last_time", 0) if throttle_data else 0

        if current_time - last_time < self.rate_limit:
            logger.debug(f"Throttling user {user_id}.")
            if isinstance(event, CallbackQuery):
                 # Отвечаем на колбек, чтобы убрать "часики"
                 await event.answer("Слишком часто!", show_alert=False)
            # Для сообщений можно ничего не делать или отправить короткое сообщение (риск флуда)
            return # Прерываем обработку

        # Обновляем время последнего запроса
        await storage.set_data(key=key, data={"last_time": current_time})

        return await handler(event, data)