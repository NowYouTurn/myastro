import logging
import asyncio
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone

# Используем Pydantic settings
from core.config import settings

# Импорты базы данных и моделей
from database import crud
from database.models import User, NatalData, Payment, Log, PaymentStatus, LogLevel

# Импорты для проверки статуса внешних сервисов
from services import openai_service, payment_service
from utils.geocoding import geocode # Импортируем geocode из utils
from geopy.exc import GeocoderServiceError, GeocoderTimedOut

logger = logging.getLogger(__name__)

async def format_user_info(
    user: User,
    natal_data: Optional[NatalData],
    payments_count: int,
    logs_count: int
) -> str:
    """Форматирует информацию о пользователе для вывода админу."""
    if not user: return "Пользователь не найден."

    referrer_info = "Нет"
    if user.referrer_id:
        # TODO: Можно добавить получение имени реферера для большей информативности
        # referrer = await crud.get_user(session, user.referrer_id)
        # referrer_info = f"{referrer.first_name} (ID: {user.referrer_id})" if referrer else f"ID: {user.referrer_id}"
        referrer_info = f"ID: {user.referrer_id}"

    natal_info = "Нет данных"
    if natal_data:
        natal_info = (f"Дата: {natal_data.birth_date}, Время: {natal_data.birth_time}, "
                      f"Город: {natal_data.birth_city} (TZ: {natal_data.timezone})")

    horoscope_time = user.daily_horoscope_time or "Не установлено"
    # Используем .isoformat() для надежного форматирования или strftime с проверкой на None
    reg_date_str = user.registration_date.strftime('%Y-%m-%d %H:%M %Z') if user.registration_date else 'N/A'
    last_act_str = user.last_activity_date.strftime('%Y-%m-%d %H:%M %Z') if user.last_activity_date else 'N/A'

    info = f"""
👤 <b>Инфо о пользователе:</b>
ID: <code>{user.id}</code>
Имя: {user.first_name or ''} {user.last_name or ''}
Username: @{user.username if user.username else '<i>-</i>'}
Язык: {user.language_code or 'N/A'}
Регистрация: {reg_date_str}
Активность: {last_act_str}

💰 <b>Баланс/Услуги:</b>
Кредиты: <b>{user.credits}</b>
Беспл. услуга: {'Да' if user.first_service_used else 'Нет'}
Условия приняты: {'Да' if user.accepted_terms else 'Нет'}

🔗 <b>Рефералы:</b>
Реф. код: <code>{user.referral_code or 'N/A'}</code>
Приглашен от: {referrer_info}
Пригласил: {len(user.referrals)} чел.

🔮 <b>Данные:</b>
Натальные: {natal_info}
Время гороскопа (UTC): {horoscope_time}

📊 <b>История (кол-во):</b>
Платежей: {payments_count}
Логов: {logs_count}
"""
    # Убираем лишние пробелы и переносы строк в начале/конце
    return "\n".join(line.strip() for line in info.strip().splitlines())


async def generate_statistics_report(session: AsyncSession) -> str:
    """Генерирует текстовый отчет со статистикой."""
    try:
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        total_users = await crud.count_total_users(session)
        new_today = await crud.count_new_users(session, day_ago)
        new_week = await crud.count_new_users(session, week_ago)
        active_today = await crud.count_active_users(session, day_ago)
        active_week = await crud.count_active_users(session, week_ago)
        horoscope_subs = await crud.count_horoscope_users(session)

        # TODO: Добавить статистику по платежам (сумма, количество) и услугам

        report = f"""
📊 <b>Статистика Бота</b> ({now.strftime('%Y-%m-%d %H:%M %Z')}):
-----------------------------------
<b>Всего пользователей:</b> {total_users}

<b>Новые пользователи:</b>
- За сегодня: {new_today}
- За неделю: {new_week}

<b>Активные пользователи:</b>
- Сегодня: {active_today}
- За неделю: {active_week}

<b>Подписки на гороскоп:</b> {horoscope_subs}

<i>(Другая статистика пока не реализована)</i>
"""
        return report.strip()
    except Exception as e:
        logger.exception("Ошибка при генерации отчета статистики")
        return "❌ Ошибка при генерации статистики."


def format_payment_list(payments: List[Payment]) -> str:
    """Форматирует список платежей."""
    if not payments: return "Платежи не найдены."
    lines = [f"🧾 <b>Последние {len(payments)} платежей:</b>"]
    for p in payments:
        status_emoji = {"SUCCEEDED": "✅", "PENDING": "⏳", "CANCELED": "❌", "WAITING_FOR_CAPTURE": "⏳"}.get(p.status.name, "❓")
        awarded_emoji = "🏆" if p.credits_awarded else ""
        created_str = p.created_at.strftime('%y-%m-%d %H:%M') if p.created_at else 'N/A'
        lines.append(f"- <code>{p.yookassa_payment_id[-12:]}</code> ({created_str}): {p.amount / 100} {p.currency} ({p.credits_purchased} кр.) Ст: {status_emoji}{awarded_emoji}")
    return "\n".join(lines)


def format_log_list(logs: List[Log]) -> str:
    """Форматирует список логов."""
    if not logs: return "Логи не найдены."
    lines = [f"📄 <b>Последние {len(logs)} логов:</b>"]
    for log in logs:
        user_info = f" U:{log.user_id}" if log.user_id else ""
        handler_info = f" [{log.handler[:15]}]" if log.handler else ""
        level_emoji = {"DEBUG": "⚙️", "INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "CRITICAL": "🔥"}.get(log.level.name, "❓")
        ts = log.timestamp.strftime('%m-%d %H:%M:%S') if log.timestamp else '?'
        message = (log.message[:100] + '...') if len(log.message) > 100 else log.message
        exception = ""
        if log.exception_info: exception = "\n  <code>" + (log.exception_info[:100] + '...') + "</code>"
        lines.append(f"{level_emoji} {ts}{user_info}{handler_info}: <i>{message}</i>{exception}")
    return "<pre>" + "\n".join(lines) + "</pre>"


async def check_external_services() -> str:
    """Проверяет статус внешних сервисов (базовая реализация)."""
    results = []
    tasks = []
    timeout = 5.0 # Таймаут для проверок

    # OpenAI
    async def check_openai():
        if openai_service.client:
            try: await asyncio.wait_for(openai_service.client.models.list(limit=1), timeout=timeout); return "✅ OpenAI: OK"
            except asyncio.TimeoutError: logger.error("Проверка OpenAI: Таймаут"); return f"❌ OpenAI: Таймаут ({timeout}s)"
            except Exception as e: logger.error(f"Проверка OpenAI: {e}"); return f"❌ OpenAI: Ошибка ({type(e).__name__})"
        else: return "❌ OpenAI: Клиент не инициализирован"
    tasks.append(check_openai())

    # YooKassa
    async def check_yookassa():
        # Реальная проверка API Юкассы сложна без выполнения операции.
        # Проверяем только конфигурацию SDK.
        return "✅ YooKassa: SDK сконфигурирован" if payment_service.YOOKASSA_ENABLED else "❌ YooKassa: SDK не настроен"
    tasks.append(check_yookassa())

    # Geocoding
    async def check_geocoding():
        try:
            # Используем asyncio.to_thread для синхронного вызова geocode
            await asyncio.wait_for(asyncio.to_thread(geocode, "Paris", language='en', timeout=timeout), timeout=timeout+1)
            return "✅ Geocoding (Nominatim): OK"
        except asyncio.TimeoutError: logger.error("Проверка Geopy: Таймаут"); return f"❌ Geocoding: Таймаут ({timeout}s)"
        except (GeocoderTimedOut, GeocoderServiceError) as e: logger.error(f"Проверка Geopy: {e}"); return f"❌ Geocoding: Ошибка сервиса ({type(e).__name__})"
        except Exception as e: logger.error(f"Проверка Geopy: {e}"); return f"❌ Geocoding: Ошибка ({type(e).__name__})"
    tasks.append(check_geocoding())

    # Запускаем проверки
    try:
        results = await asyncio.gather(*tasks)
    except Exception as e:
         logger.error(f"Ошибка при выполнении проверок сервисов: {e}")
         return "❌ Не удалось выполнить проверку статуса сервисов."

    return "⚙️ <b>Статус внешних сервисов:</b>\n" + "\n".join(results)