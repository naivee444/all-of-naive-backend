from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import User, Log

async def upsert_user(s: AsyncSession, tg_id: int, username: str | None, first_name: str | None):
    user = (await s.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
    if not user:
        user = User(tg_id=tg_id, username=username, first_name=first_name)
        s.add(user)
        s.add(Log(tg_id=tg_id, action="user_start", payload=""))
    else:
        user.username = username
        user.first_name = first_name
    await s.commit()
    return user
