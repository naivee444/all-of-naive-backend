from datetime import datetime
from sqlalchemy import select
from aiogram import Bot
from ..db import SessionLocal, Subscription, Log
from ..config import settings

async def kick_expired(bot: Bot):
    async with SessionLocal() as s:
        result = await s.execute(select(Subscription).where(Subscription.active == True, Subscription.expires_at <= datetime.utcnow()))
        for sub in result.scalars().all():
            try:
                await bot.ban_chat_member(settings.PRIVATE_GROUP_ID, sub.tg_id)
                await bot.unban_chat_member(settings.PRIVATE_GROUP_ID, sub.tg_id, only_if_banned=True)
                sub.active = False
                s.add(Log(tg_id=sub.tg_id, action="expired_autokick", payload=""))
            except Exception as e:
                s.add(Log(tg_id=sub.tg_id, action="autokick_error", payload=str(e)))
        await s.commit()
