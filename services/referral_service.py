import logging
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot

from database import crud
from database.models import LogLevel # Импорт LogLevel
from services import user_service
from core.config import settings

logger = logging.getLogger(__name__)

async def award_referral_bonus_if_applicable(session: AsyncSession, bot: Bot, referred_user_id: int):
    """ Проверяет и начисляет реферальный бонус после первой бесплатной услуги. """
    try:
        referred_user = await crud.get_user(session, referred_user_id)
        if not referred_user or not referred_user.referrer_id: # Нет юзера или реферера
            logger.debug(f"[Referral Bonus] No referrer for user {referred_user_id}.")
            return
        # Проверяем, что это действительно была первая бесплатная услуга
        # Флаг first_service_used уже должен быть True к моменту вызова этой функции
        if not referred_user.first_service_used:
             logger.warning(f"[Referral Bonus] Attempt award bonus but first service not marked used for user {referred_user_id}.")
             return # Не начисляем, если флаг еще не стоит

        # Проверим, не начисляли ли уже бонус за этого реферала этому рефереру
        # TODO: Это требует доп. логики/флага, например, в таблице User или отдельной таблице бонусов.
        # Пока пропускаем эту проверку для простоты - бонус будет начисляться КАЖДЫЙ раз,
        # когда вызывается эта функция для пользователя с реферером, если free_service_used=True.
        # Это НЕПРАВИЛЬНО для реальной системы! Нужно доработать.
        # --- Начало Начисления (упрощенное) ---
        referrer = await crud.get_user(session, referred_user.referrer_id)
        if not referrer: logger.warning(f"[Referral Bonus] Referrer {referred_user.referrer_id} not found."); return

        bonus_credits = settings.service_cost
        new_balance = await crud.update_user_credits(session, referrer.id, bonus_credits)
        if new_balance is not None:
            log_msg = (f"[Referral Bonus] Awarded {bonus_credits} credits to user {referrer.id} "
                       f"for friend's ({referred_user_id}) first free service. New balance: {new_balance}")
            logger.info(log_msg); await crud.add_log_entry(session, LogLevel.INFO, log_msg, referrer.id, "referral_bonus")
            await user_service.notify_referrer_bonus(bot, referrer.id, referred_user.first_name or f"ID:{referred_user_id}", bonus_credits)
        else: logger.error(f"[Referral Bonus] Failed awarding bonus to referrer {referrer.id}.")
        # --- Конец Начисления ---

    except Exception as e:
        logger.exception(f"[Referral Bonus] Error awarding bonus for referred user {referred_user_id}: {e}")