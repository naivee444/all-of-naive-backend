from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Log, User


async def upsert_user(
    s: AsyncSession,
    tg_id: int,
    username: str | None,
    first_name: str | None,
    language: str | None = "ru",
):
    """
    Safe create/update for Telegram user.

    Fixes:
    sqlite3.IntegrityError: UNIQUE constraint failed: users.tg_id
    """
    tg_id = int(tg_id)
    lang = language or "ru"

    user = (
        await s.execute(select(User).where(User.tg_id == tg_id))
    ).scalar_one_or_none()

    if user:
        user.username = username
        user.first_name = first_name
        user.language = lang
        await s.commit()
        return user

    user = User(
        tg_id=tg_id,
        username=username,
        first_name=first_name,
        language=lang,
    )
    s.add(user)
    s.add(Log(tg_id=tg_id, action="user_upsert", payload="created"))

    try:
        await s.commit()
    except IntegrityError:
        await s.rollback()
        user = (
            await s.execute(select(User).where(User.tg_id == tg_id))
        ).scalar_one_or_none()
        if user:
            user.username = username
            user.first_name = first_name
            user.language = lang
            await s.commit()
            return user
        raise

    await s.refresh(user)
    return user
