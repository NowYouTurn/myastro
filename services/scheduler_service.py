import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from datetime import datetime, time, timezone
import pytz
from aiogram import Bot

# Используем Pydantic settings
from core.config import settings
from database.database import async_session_factory # Импортируем фабрику сессий

logger = logging.getLogger(__name__)

# Настройка хранилища (используем СИНХРОННЫЙ URL из настроек)
jobstores = {'default': SQLAlchemyJobStore(url=settings.sync_database_url)}
executors = {'default': AsyncIOExecutor()}
job_defaults = {'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 300}

scheduler = AsyncIOScheduler(
    jobstores=jobstores, executors=executors, job_defaults=job_defaults, timezone=pytz.utc
)

def start_scheduler():
    try:
        if not scheduler.running: scheduler.start(); logger.info("[Scheduler] Started.")
        else: logger.warning("[Scheduler] Already running.")
    except Exception as e: logger.exception(f"[Scheduler] Start error: {e}")

def shutdown_scheduler():
    try:
        if scheduler.running: scheduler.shutdown(wait=False); logger.info("[Scheduler] Stopped.")
    except Exception as e: logger.exception(f"[Scheduler] Stop error: {e}")

# --- Задача рассылки гороскопов ---
async def send_daily_horoscopes_job(bot: Bot):
    # Импорты внутри для предотвращения циклов и доступа к сессии/боту
    from database import crud
    from services.astrology_service import get_natal_data_kerykeion, get_daily_horoscope_interpretation
    from services.user_service import notify_user
    from utils.date_time_helpers import get_current_utc_time_str

    current_utc_time_str = get_current_utc_time_str()
    logger.info(f"[Scheduler] Running horoscope job for {current_utc_time_str} UTC.")

    try: # Оборачиваем весь блок работы с сессией
        async with async_session_factory() as session: # Получаем сессию из фабрики
            users_to_notify = await crud.get_users_for_daily_horoscope(session, current_utc_time_str)
            if not users_to_notify: logger.info(f"[Scheduler] No users for {current_utc_time_str}."); return
            logger.info(f"[Scheduler] Found {len(users_to_notify)} users for {current_utc_time_str}.")

            for user in users_to_notify:
                # Проверка данных перед расчетом
                if not user.accepted_terms: logger.warning(f"[Scheduler] Skip user {user.id}: terms not accepted."); continue
                # natal_data проверяется JOIN'ом в crud.get_users_for_daily_horoscope
                # Доп. проверка на всякий случай
                natal_data = await crud.get_natal_data(session, user.id)
                if not natal_data: logger.warning(f"[Scheduler] Skip user {user.id}: natal data not found (should not happen)."); continue

                logger.debug(f"[Scheduler] Processing user {user.id} ({user.first_name}).")
                try: # Обработка ошибок для одного пользователя
                    kr_instance = await get_natal_data_kerykeion(
                        first_name=user.first_name, birth_date=natal_data.birth_date, birth_time=natal_data.birth_time,
                        city_name=natal_data.birth_city, latitude=natal_data.latitude, longitude=natal_data.longitude,
                        timezone_str=natal_data.timezone )
                    if not kr_instance: logger.error(f"[Scheduler] Failed KrInstance user {user.id}."); continue
                    horoscope_text = await get_daily_horoscope_interpretation(kr_instance)
                    if await notify_user(bot, user.id, horoscope_text): logger.debug(f"[Scheduler] Sent to user {user.id}.")
                    else: logger.error(f"[Scheduler] Failed sending to user {user.id}.")
                except Exception as user_e: logger.exception(f"[Scheduler] Error processing horoscope for user {user.id}: {user_e}")
                await asyncio.sleep(0.1) # Пауза для избежания лимитов Telegram

    except Exception as e: logger.exception(f"[Scheduler] Global error in horoscope job: {e}")
    logger.info(f"[Scheduler] Finished horoscope job for {current_utc_time_str} UTC.")


def setup_scheduler_jobs(bot: Bot):
    """ Настраивает задачи планировщика при старте бота. """
    try:
         scheduler.add_job(
             send_daily_horoscopes_job, trigger='cron', minute='*', # Каждую минуту
             id='master_horoscope_sender', name='Master Horoscope Sender',
             replace_existing=True, max_instances=1, args=[bot] )
         logger.info("[Scheduler] Master horoscope sender job scheduled.")
    except Exception as e: logger.exception("[Scheduler] Error scheduling horoscope job.")
    # TODO: Добавить другие периодические задачи (например, очистка папки temp)