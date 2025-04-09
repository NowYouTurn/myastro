from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

class DbSessionMiddleware(BaseMiddleware):
    """ Middleware для предоставления сессии SQLAlchemy в хендлеры. """
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        super().__init__(); self.session_factory = session_factory

    async def __call__(self, handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]], event: Update, data: Dict[str, Any]) -> Any:
        async with self.session_factory() as session:
            data['session'] = session; return await handler(event, data)