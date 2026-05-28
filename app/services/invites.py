from aiogram import Bot
from datetime import datetime, timedelta
from ..config import settings

async def create_one_time_invite(bot: Bot, tg_id: int) -> str:
    link = await bot.create_chat_invite_link(
        chat_id=settings.PRIVATE_GROUP_ID,
        name=f"AllOfNaive_{tg_id}",
        expire_date=datetime.utcnow() + timedelta(hours=24),
        member_limit=1,
        creates_join_request=True,
    )
    return link.invite_link
