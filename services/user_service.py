import logging
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramNotFound, TelegramRetryAfter

# Используем Pydantic settings
from core.config import settings

from database import crud
from database.models import User, NatalData # Импорт моделей

logger = logging.getLogger(__name__)

async def check_service_availability(
    session: AsyncSession, user_id: int
) -> Tuple[bool, int, bool, str]:
    """ Проверяет доступность платной услуги. """
    user = await crud.get_user(session, user_id)
    if not user: return False, 0, False, "Ошибка: Профиль не найден."

    credits = user.credits
    # Используем настройки из Pydantic
    is_free_available = settings.first_service_free and not user.first_service_used
    service_cost = settings.service_cost

    if credits >= service_cost:
        msg = f"У вас {credits} кр. Услуга стоит {service_cost} кр."
        return True, credits, False, msg
    elif is_free_available:
        msg = "✨ Доступна первая бесплатная услуга!"
        return True, credits, True, msg
    else:
        msg = f"У вас {credits} кр. Нужно {service_cost} кр.\nКупите кредиты."
        return False, credits, False, msg

async def use_service_credit(session: AsyncSession, user_id: int) -> bool:
    """ Списывает кредит за услугу (НЕ обрабатывает бесплатную). """
    # Эта функция вызывается ТОЛЬКО для платного использования
    # Бесплатное использование обрабатывается отдельно с вызовом crud.mark_first_service_used
    service_cost = settings.service_cost
    new_balance = await crud.update_user_credits(session, user_id, -service_cost)
    # crud.update_user_credits вернет None при ошибке или нехватке средств
    return new_balance is not None


async def has_natal_data(session: AsyncSession, user_id: int) -> bool:
    """ Проверяет наличие натальных данных. """
    natal_data = await crud.get_natal_data(session, user_id)
    return natal_data is not None


# Функция get_user_or_register не используется в текущей логике handle_start, можно удалить или оставить для других нужд
# async def get_user_or_register(...) -> Optional[User]: ...


# --- Функции уведомлений ---
async def notify_user(bot: Bot, user_id: int, message: str, keyboard=None, parse_mode="HTML") -> bool:
    """ Безопасная отправка сообщения пользователю с обработкой ошибок. """
    try:
        await bot.send_message(user_id, message, reply_markup=keyboard, parse_mode=parse_mode, disable_web_page_preview=True)
        logger.debug(f"Сообщение успешно отправлено user {user_id}")
        return True
    except TelegramRetryAfter as e:
        logger.warning(f"Flood limit exceeded for user {user_id}. Sleeping for {e.retry_after}s.")
        await asyncio.sleep(e.retry_after)
        return await notify_user(bot, user_id, message, keyboard, parse_mode) # Рекурсивный вызов после паузы
    except (TelegramForbiddenError, TelegramNotFound) as e:
        # Бот заблокирован, пользователь удален или не существует
        logger.warning(f"Cannot send message to user {user_id}: {e}. User might have blocked the bot or is deactivated.")
        # TODO: Можно добавить логику деактивации пользователя в БД
        # await crud.deactivate_user(session, user_id)
        return False
    except TelegramAPIError as e: # Другие ошибки API
        logger.error(f"Failed to send message to user {user_id}: {e}")
        return False
    except Exception as e: # Непредвиденные ошибки
        logger.exception(f"Unexpected error sending message to user {user_id}: {e}")
        return False


async def notify_payment_success(bot: Bot, user_id: int, credits_purchased: int):
    """ Уведомляет пользователя об успешной оплате. """
    message = settings.PAYMENT_THANK_YOU.format(credits=credits_purchased)
    await notify_user(bot, user_id, message)

async def notify_payment_failure(bot: Bot, user_id: int, reason: str = ""):
    """ Уведомляет пользователя о неудачной оплате. """
    message = settings.PAYMENT_ERROR + (f"\nПричина: {reason}" if reason else "")
    await notify_user(bot, user_id, message)

async def notify_referrer_bonus(bot: Bot, referrer_id: int, referred_user_name: str, bonus_credits: int):
    """ Уведомляет реферера о начислении бонуса. """
    message = (f"🎉 Ваш друг {referred_user_name} воспользовался первой бесплатной услугой!"
               f"\nВам начислен бонус: {bonus_credits} кредит(а).\nСпасибо, что приглашаете друзей!")
    await notify_user(bot, referrer_id, message)

# Импорт asyncio для sleep
import asyncio