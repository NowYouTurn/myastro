import asyncio
import logging
import ssl
import ipaddress
from typing import Dict, Any, Callable, Awaitable, Optional # Добавлены Optional, Any

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext # Импорт FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.types import Update, BotCommand, BotCommandScopeDefault

from aiohttp import web
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

# Импорт Pydantic настроек
from core.config import settings

# Импорт базы данных и middleware
from database.database import init_models, async_session_factory
from middlewares.db import DbSessionMiddleware
from middlewares.logging import LoggingContextMiddleware
from middlewares.throttling import ThrottlingMiddleware

# Импорт утилит и сервисов
from utils.logging_config import setup_logging
from services import scheduler_service, payment_service # Импорт payment_service

# Импорт роутеров
from handlers import (
    common, astrology, horoscope, other_services,
    palmistry, payment, referral, admin
)

# --- Инициализация Sentry (если настроен DSN) ---
if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.aiohttp import AioHttpIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_logging = LoggingIntegration(
            level=logging.INFO,        # INFO и выше как breadcrumbs
            event_level=logging.ERROR  # ERROR и выше как события Sentry
        )
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[ AioHttpIntegration(), SqlalchemyIntegration(), sentry_logging ],
            traces_sample_rate=1.0, profiles_sample_rate=1.0, send_default_pii=False )
        logging.info("Sentry SDK инициализирован.")
    except ImportError: logging.warning("Sentry DSN указан, но 'sentry-sdk' не найден.")
    except Exception as e: logging.exception(f"Ошибка инициализации Sentry: {e}")


# --- Обработчик вебхука ЮKassa ---
async def handle_yookassa_webhook(request: web.Request):
    bot = request.app['bot']
    session_factory = request.app['session_factory']
    remote_ip_str = request.remote
    logger = logging.getLogger(__name__)
    logger.debug(f"[Webhook YooKassa] Запрос от {remote_ip_str} на {settings.yookassa_webhook_path}")
    try: # Проверка IP
        remote_ip = ipaddress.ip_address(remote_ip_str)
        if not any(remote_ip in ipaddress.ip_network(net) for net in settings.yookassa_ips):
            logger.warning(f"[Webhook YooKassa] Недоверенный IP: {remote_ip_str}. Отказ."); return web.Response(status=403)
    except ValueError: logger.warning(f"[Webhook YooKassa] Не распознан IP: {remote_ip_str}. Отказ."); return web.Response(status=400)
    try: # Обработка данных
        data = await request.json(); logger.info(f"[Webhook YooKassa] Данные: {str(data)[:500]}...")
        async with session_factory() as session: # Создаем сессию
            success = await payment_service.process_yookassa_notification(session=session, bot=bot, notification_data=data)
        if success: logger.info(f"[Webhook YooKassa] Успешно обработано."); return web.Response(status=200)
        else: logger.error(f"[Webhook YooKassa] Ошибка обработки."); return web.Response(status=500)
    except Exception as e: logger.exception(f"[Webhook YooKassa] Непредвиденная ошибка: {e}"); return web.Response(status=500)


# --- Функции жизненного цикла ---
async def on_startup(bot: Bot, dp: Dispatcher):
    logger = logging.getLogger(__name__)
    logger.info("Выполняется on_startup...")
    try: await init_models() # Проверка соединения с БД
    except Exception as e: logger.critical(f"Критическая ошибка БД: {e}.", exc_info=True); raise
    #if not settings.webhook_domain: logger.critical("WEBHOOK_DOMAIN не задан!"); raise ValueError("WEBHOOK_DOMAIN не сконфигурирован")
    #webhook_url = f"{settings.base_webhook_url}{settings.telegram_webhook_path}"
    #try:
        #await bot.set_webhook( url=webhook_url, secret_token=settings.telegram_webhook_secret.get_secret_value(),
            #allowed_updates=dp.resolve_used_update_types() )
        #logger.info(f"Вебхук Telegram установлен: {webhook_url}")
    #except Exception as e: logger.error(f"Ошибка установки вебхука Telegram: {e}", exc_info=True); raise
    scheduler_service.setup_scheduler_jobs(bot); scheduler_service.start_scheduler()
    commands = [ BotCommand(command="start", description="🚀 Запустить/Перезапустить бота"),
                 BotCommand(command="help", description="ℹ️ Помощь и описание команд"),
                 BotCommand(command="menu", description="🏠 Показать главное меню"), ]
    try: await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    except Exception as e: logger.warning(f"Не удалось установить команды меню: {e}")
    logger.info("Бот готов к работе!")

async def on_shutdown(bot: Bot):
    #logger = logging.getLogger(__name__)
    #logger.info("Выполняется on_shutdown...")
    #scheduler_service.shutdown_scheduler()
    #logger.info("Удаление вебхука Telegram...")
    #try:
    #    if bot.token: await bot.delete_webhook(drop_pending_updates=True) # Сбрасываем обновления при остановке
    #    else: logger.warning("Токен бота отсутствует, пропуск удаления вебхука.")
    #except Exception as e: logger.error(f"Ошибка удаления вебхука: {e}", exc_info=True)
    #logger.info("Закрытие сессии бота...")
    #try:
    #    if bot.session and not bot.session.closed: await bot.session.close()
    #except Exception as e: logger.error(f"Ошибка закрытия сессии бота: {e}", exc_info=True)
    #logger.info("Ресурсы освобождены.")


# --- Основная точка входа ---
    def main():
    # Настройка логирования
        setup_logging() # Использует настройки из Pydantic
    logger = logging.getLogger(__name__)
    logger.info(f"Запуск бота в режиме вебхука (Порт: {settings.webhook_server_port})...")

    if not settings.webhook_domain or not settings.telegram_webhook_path:
        logger.critical("WEBHOOK_DOMAIN или TELEGRAM_WEBHOOK_PATH не задан! Запуск невозможен.")
        return

    # Инициализация Aiogram
    storage = MemoryStorage() # Для FSM (можно заменить на RedisStorage для масштабирования)
    bot = Bot(token=settings.telegram_bot_token.get_secret_value(), parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=storage)

    # Регистрация Middleware (порядок важен!)
    dp.update.outer_middleware(LoggingContextMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware(session_factory=async_session_factory))
    dp.message.middleware(ThrottlingMiddleware(storage=storage)) # Передаем storage в троттлинг
    dp.callback_query.middleware(ThrottlingMiddleware(storage=storage))
    dp.callback_query.middleware(CallbackAnswerMiddleware())

    # Регистрация роутеров
    logger.info("Регистрация роутеров...")
    dp.include_router(admin.admin_router) # Админский роутер первым
    dp.include_router(common.common_router)
    dp.include_router(astrology.astrology_router)
    dp.include_router(horoscope.horoscope_router)
    dp.include_router(other_services.other_services_router)
    dp.include_router(palmistry.palmistry_router)
    dp.include_router(payment.payment_router)
    dp.include_router(referral.referral_router)

    # Регистрация хуков startup/shutdown
    dp.startup.register(lambda dispatcher=dp: on_startup(bot, dispatcher))
    dp.shutdown.register(lambda: on_shutdown(bot))

    # Настройка и запуск веб-приложения aiohttp
    #app = web.Application()
    #app['bot'] = bot
    #app['session_factory'] = async_session_factory

    # Роут для вебхука ЮKassa
    #app.router.add_post(settings.yookassa_webhook_path, handle_yookassa_webhook)

    # Роут для вебхука Telegram
    #webhook_requests_handler = SimpleRequestHandler(
    #    dispatcher=dp,
    #    bot=bot,
    #    secret_token=settings.telegram_webhook_secret.get_secret_value()
    #)
    #webhook_requests_handler.register(app, path=settings.telegram_webhook_path)

    # Связываем жизненный цикл Aiogram и aiohttp
    #setup_application(app, dp, bot=bot)

    # Запуск веб-сервера
    # Настройки SSL должны быть здесь, если НЕ используется обратный прокси
    # ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # ssl_context.load_cert_chain('path/to/fullchain.pem', 'path/to/privkey.pem')
    #logger.info(f"Запуск веб-сервера на http://{settings.webhook_server_listen_host}:{settings.webhook_server_port}")
    #web.run_app(
    #    app,
    #    host=settings.webhook_server_listen_host,
    #    port=settings.webhook_server_port,
        # ssl_context=ssl_context # Раскомментировать для HTTPS напрямую
    #)

    if __name__ == "__main__":
        try:
            main()
        except (KeyboardInterrupt, SystemExit):
            logging.getLogger(__name__).info("Бот остановлен.")
        except Exception as e:
            logging.getLogger(__name__).critical(f"Критическая ошибка запуска: {e}", exc_info=True)