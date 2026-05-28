from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import Subscription, Plan, Log

async def grant_subscription(s: AsyncSession, tg_id: int, plan_id: str):
    plan = await s.get(Plan, plan_id)
    if not plan:
        raise ValueError("Plan not found")
    now = datetime.utcnow()
    sub = (await s.execute(select(Subscription).where(Subscription.tg_id == tg_id, Subscription.active == True))).scalar_one_or_none()
    base = sub.expires_at if sub and sub.expires_at > now else now
    expires = base + timedelta(days=plan.days)
    if sub:
        sub.plan_id = plan_id
        sub.expires_at = expires
        sub.active = True
    else:
        sub = Subscription(tg_id=tg_id, plan_id=plan_id, starts_at=now, expires_at=expires, active=True)
        s.add(sub)
    s.add(Log(tg_id=tg_id, action="subscription_granted", payload=f"{plan_id} until {expires.isoformat()}"))
    await s.commit()
    return sub
