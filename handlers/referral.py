import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.utils.markdown import hbold, hcode

from sqlalchemy.ext.asyncio import AsyncSession

from keyboards import reply
from database import crud
from utils.referral_utils import generate_referral_link
from core.config import settings

referral_router = Router()
logger = logging.getLogger(__name__)

@referral_router.message(F.text == "🎁 Реферальная программа")
async def cmd_referral(message: Message, session: AsyncSession):
    user_id = message.from_user.id; user = await crud.get_user(session, user_id)
    if not user: await message.answer("Ошибка профиля."); return
    if not user.referral_code: # Генерация кода при первом запросе
        user.referral_code = await crud.generate_unique_referral_code(session)
        try: await session.commit(); await session.refresh(user); logger.info(f"Сгенерирован реф. код {user.referral_code} user {user_id}")
        except Exception as e: logger.exception(f"Ошибка сохр. реф. кода user {user_id}: {e}"); await session.rollback(); await message.answer("Ошибка генерации кода."); return

    ref_link = generate_referral_link(user.referral_code); ref_count = await crud.count_referrals(session, user_id); bonus = settings.service_cost

    text = f"""
{hbold('🎁 Реферальная программа')}

Приглашайте друзей и получайте бонусы!

{hbold('Как это работает:')}
1. Поделитесь вашей ссылкой:
   <code>{ref_link}</code>
   <i>(Нажмите на ссылку для копирования)</i>

2. Когда друг перейдет по ссылке, запустит бота и воспользуется {hbold('первой бесплатной услугой')}, вы получите бонус: {hbold(bonus)} кредит(а)! ✨

{hbold('Ваша статистика:')}
- Ваш код: {hcode(user.referral_code)}
- Приглашено друзей: {ref_count}

Делитесь ссылкой и получайте больше возможностей! 💜
"""
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    await message.answer("Главное меню:", reply_markup=reply.get_main_menu(user_id))