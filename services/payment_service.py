import logging
import uuid
import asyncio
from typing import Optional, Dict, Any, Tuple
from yookassa import Configuration, Payment as YooKassaPayment
from yookassa.domain.response import PaymentResponse
from yookassa.domain.exceptions import (
    ApiError, BadRequestError, ForbiddenError, InternalServerError,
    NotFoundError, ResponseProcessingError, TooManyRequestsError, UnauthorizedError
)
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot

# Используем Pydantic settings
from core.config import settings

# Импорт CRUD и моделей
import database.crud as crud
from database.models import PaymentStatus, Payment

# Импорт user_service для уведомлений об оплате
from services import user_service

logger = logging.getLogger(__name__)

# --- YooKassa Configuration ---
YOOKASSA_ENABLED = False
if settings.yookassa_shop_id and settings.yookassa_secret_key:
    try:
        Configuration.configure(settings.yookassa_shop_id, settings.yookassa_secret_key.get_secret_value())
        logger.info("YooKassa SDK сконфигурирован.")
        YOOKASSA_ENABLED = True
    except Exception as e: logger.exception(f"Ошибка конфигурации YooKassa SDK: {e}")
else: logger.warning("YooKassa Shop ID/Secret Key не установлены.")


async def create_yookassa_payment(
    session: AsyncSession, user_id: int, amount_rub: int, credits_to_add: int, payment_option_key: str
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not YOOKASSA_ENABLED: logger.error(f"Create payment user {user_id}: YooKassa disabled."); return None, None, "Платежный сервис отключен."

    amount_kopecks = amount_rub * 100
    description = f"Покупка {credits_to_add} кр. ({settings.PAYMENT_OPTIONS.get(payment_option_key,{}).get('description','')}) user:{user_id}"
    idempotence_key = str(uuid.uuid4())
    return_url = settings.base_webhook_url or "https://t.me/" # Куда вернуть пользователя

    payment_data = {
        "amount": {"value": f"{amount_kopecks / 100:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "capture": True, "description": description,
        "metadata": {"user_id": str(user_id), "credits": str(credits_to_add), "key": payment_option_key, "idempotence": idempotence_key},
        # "receipt": { ... } # Добавить при необходимости
    }

    logger.info(f"Create payment user {user_id}, amount: {amount_rub}, credits: {credits_to_add}, key: {idempotence_key}")
    try:
        payment_response: PaymentResponse = await asyncio.to_thread(YooKassaPayment.create, payment_data, idempotence_key)
        logger.info(f"Payment created: ID={payment_response.id}, Status={payment_response.status}")
        db_payment = await crud.create_payment(session, user_id, payment_response.id, amount_kopecks, credits_to_add, description)
        if not db_payment: logger.error(f"Failed save payment {payment_response.id} to DB!"); return None, None, "Ошибка БД."
        if payment_response.confirmation and payment_response.confirmation.confirmation_url:
            logger.info(f"Confirmation URL user {user_id}: {payment_response.confirmation.confirmation_url}")
            return payment_response.confirmation.confirmation_url, payment_response.id, None
        else: logger.error(f"No confirmation_url for payment {payment_response.id}"); return None, payment_response.id, "Нет ссылки на оплату."
    except UnauthorizedError: logger.error(f"Auth Error YooKassa user {user_id}."); return None, None, "Ошибка конфигурации платежей."
    except ForbiddenError: logger.error(f"Forbidden YooKassa user {user_id}."); return None, None, "Ошибка доступа к платежам."
    except BadRequestError as e: logger.exception(f"Bad Request YooKassa user {user_id}: {e}"); return None, None, f"Ошибка параметров: {getattr(e, 'message', '')}"
    except TooManyRequestsError: logger.warning(f"Rate Limit YooKassa user {user_id}."); return None, None, "Слишком много запросов, попробуйте позже."
    except InternalServerError as e: logger.error(f"Internal Error YooKassa user {user_id}: {e}"); return None, None, "Ошибка сервера платежей."
    except ApiError as e: logger.exception(f"API Error YooKassa user {user_id}: {e}"); return None, None, f"Ошибка API платежей: {getattr(e, 'message', type(e).__name__)}"
    except Exception as e: logger.exception(f"Unexpected error create payment user {user_id}: {e}"); return None, None, "Внутренняя ошибка."


async def check_yookassa_payment_status(session: AsyncSession, yookassa_payment_id: str) -> Tuple[Optional[PaymentStatus], Optional[int]]:
    if not YOOKASSA_ENABLED: return None, None
    logger.info(f"[Manual Check] Check status payment {yookassa_payment_id}")
    try:
        payment_info: PaymentResponse = await asyncio.to_thread(YooKassaPayment.find_one, yookassa_payment_id)
        status = payment_info.status; logger.info(f"[Manual Check] YooKassa status {yookassa_payment_id}: {status}")
        new_status = {"succeeded": PaymentStatus.SUCCEEDED, "canceled": PaymentStatus.CANCELED, "waiting_for_capture": PaymentStatus.WAITING_FOR_CAPTURE}.get(status, PaymentStatus.PENDING)
        db_payment = await crud.get_payment_by_yookassa_id(session, yookassa_payment_id)
        if not db_payment: logger.warning(f"[Manual Check] Payment {yookassa_payment_id} not in DB."); return new_status, None
        if db_payment.status != new_status:
            await crud.update_payment_status(session, yookassa_payment_id, new_status)
            logger.info(f"[Manual Check] DB Status updated {yookassa_payment_id} -> {new_status.name}")
        return new_status, db_payment.user_id
    except NotFoundError: logger.warning(f"[Manual Check] Payment {yookassa_payment_id} not found in YooKassa."); await crud.update_payment_status(session, yookassa_payment_id, PaymentStatus.CANCELED); return PaymentStatus.CANCELED, None
    except Exception as e: logger.exception(f"[Manual Check] Error check status {yookassa_payment_id}: {e}"); return None, None


async def process_yookassa_notification(session: AsyncSession, bot: Bot, notification_data: Dict[str, Any]) -> bool:
    if not YOOKASSA_ENABLED: logger.error("[Webhook] YooKassa disabled."); return False
    try:
        event, payment_obj = notification_data.get('event'), notification_data.get('object')
        if not event or not payment_obj or payment_obj.get('type') != 'payment': logger.warning(f"[Webhook] Invalid notification: {notification_data}"); return True
        payment_id, status_notif = payment_obj.get('id'), payment_obj.get('status')
        if not payment_id or not status_notif: logger.warning(f"[Webhook] No ID or Status: {notification_data}"); return True
        logger.info(f"[Webhook] Notification: {payment_id=}, {status_notif=}, {event=}")
        db_payment = await crud.get_payment_by_yookassa_id(session, payment_id)
        if not db_payment: logger.error(f"[Webhook] Payment {payment_id} not in DB."); return True # Отвечаем ОК

        new_status = {"succeeded": PaymentStatus.SUCCEEDED, "canceled": PaymentStatus.CANCELED, "waiting_for_capture": PaymentStatus.WAITING_FOR_CAPTURE}.get(status_notif, PaymentStatus.PENDING)
        needs_update = db_payment.status != new_status
        is_success = new_status == PaymentStatus.SUCCEEDED
        already_awarded = db_payment.credits_awarded

        if needs_update: await crud.update_payment_status(session, payment_id, new_status); logger.info(f"[Webhook] DB Status updated {payment_id} -> {new_status.name}.")

        if is_success and not already_awarded:
            logger.info(f"[Webhook] Payment {payment_id} succeeded. Awarding credits.")
            user_id, credits = db_payment.user_id, db_payment.credits_purchased
            new_balance = await crud.update_user_credits(session, user_id, credits)
            if new_balance is not None:
                await crud.mark_payment_credits_awarded(session, payment_id)
                logger.info(f"[Webhook] Credits ({credits}) awarded user {user_id}. Balance: {new_balance}")
                await user_service.notify_payment_success(bot, user_id, credits) # Уведомляем пользователя
                # Реферальный бонус теперь не здесь
            else: logger.error(f"[Webhook] Failed awarding credits user {user_id} payment {payment_id}"); return False # Ошибка обработки
        elif is_success and already_awarded: logger.info(f"[Webhook] Payment {payment_id} already awarded.")
        elif new_status == PaymentStatus.CANCELED: logger.info(f"[Webhook] Payment {payment_id} canceled.")

        return True # Уведомление обработано
    except Exception as e: logger.exception(f"[Webhook] Unexpected error processing notification: {e}"); return False