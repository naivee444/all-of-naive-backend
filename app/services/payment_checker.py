from sqlalchemy import select
from aiogram import Bot
from ..db import SessionLocal, Payment, Log
from .payments import check_provider_payment_status, mark_payment_paid
from .subscriptions import grant_subscription
from .invites import create_one_time_invite


async def confirm_payment_if_paid(bot: Bot, payment_id: int) -> bool:
    async with SessionLocal() as s:
        payment = await s.get(Payment, payment_id)
        if not payment or payment.status != "pending":
            return False
        status = await check_provider_payment_status(payment)
        if status == "paid":
            invite = None
            try:
                invite = await create_one_time_invite(bot, payment.tg_id)
            except Exception as e:
                s.add(Log(tg_id=payment.tg_id, action="invite_error", payload=str(e)))
            await mark_payment_paid(s, payment, invite)
            sub = await grant_subscription(s, payment.tg_id, payment.plan_id)
            try:
                text = (
                    "Оплата подтверждена.exe\n\n"
                    f"Подписка активна до {sub.expires_at:%d.%m.%Y %H:%M}.\n"
                )
                if invite:
                    text += f"\nТвоя одноразовая ссылка в Naive PRIVATE:\n{invite}\n\nЗаявку проверит владелец."
                else:
                    text += "\nСсылка не создана автоматически. Напиши владельцу, он проверит оплату в админке."
                await bot.send_message(payment.tg_id, text)
            except Exception as e:
                s.add(Log(tg_id=payment.tg_id, action="paid_notify_error", payload=str(e)))
                await s.commit()
            return True
        if status == "canceled":
            payment.status = "canceled"
            s.add(Log(tg_id=payment.tg_id, action="payment_canceled", payload=f"payment_id={payment.id}"))
            await s.commit()
        return False


async def check_pending_payments(bot: Bot):
    async with SessionLocal() as s:
        rows = (await s.execute(select(Payment).where(Payment.status == "pending").limit(25))).scalars().all()
        ids = [p.id for p in rows]
    for pid in ids:
        try:
            await confirm_payment_if_paid(bot, pid)
        except Exception:
            # keep scheduler alive no matter what
            pass
