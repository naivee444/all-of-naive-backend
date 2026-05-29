from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import Log, Payment, Plan, PromoCode


def _rub(value: int) -> str:
    return str(Decimal(int(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


async def _apply_promo(
    s: AsyncSession,
    amount: int,
    promo: str | None,
) -> tuple[int, str, PromoCode | None]:
    if not promo:
        return amount, "", None

    code = promo.strip().upper()
    promo_obj = await s.get(PromoCode, code)
    if not promo_obj or not promo_obj.active or promo_obj.uses_left <= 0:
        return amount, "promo_invalid", None

    discount = max(0, min(100, int(promo_obj.discount_percent)))
    new_amount = int(amount * (100 - discount) / 100)
    return max(new_amount, 1), f"promo={code};discount={discount}%", promo_obj


async def _create_yookassa_payment(payment: Payment, plan: Plan) -> str | None:
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise RuntimeError("YooKassa keys are missing")

    payload = {
        "amount": {"value": _rub(payment.amount_rub), "currency": "RUB"},
        "capture": True,
        "description": f"All Of Naive: {plan.title_ru}",
        "confirmation": {
            "type": "redirect",
            "return_url": settings.WEBAPP_URL,
        },
        "metadata": {
            "payment_id": str(payment.id),
            "tg_id": str(payment.tg_id),
            "plan_id": payment.plan_id,
        },
    }
    headers = {"Idempotence-Key": str(uuid.uuid4())}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.yookassa.ru/v3/payments",
            auth=(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY),
            headers=headers,
            json=payload,
        )

    if r.status_code >= 400:
        raise RuntimeError(f"YooKassa error {r.status_code}: {r.text[:500]}")

    data = r.json()
    payment.provider_payment_id = data.get("id")
    return data.get("confirmation", {}).get("confirmation_url")


async def _create_cryptobot_invoice(payment: Payment, plan: Plan) -> str | None:
    if not settings.CRYPTOBOT_TOKEN:
        raise RuntimeError("CryptoBot token is missing")

    payload = {
        "currency_type": "fiat",
        "fiat": "RUB",
        "amount": _rub(payment.amount_rub),
        "description": f"All Of Naive: {plan.title_ru}",
        "payload": str(payment.id),
        "expires_in": 3600,
    }
    headers = {"Crypto-Pay-API-Token": settings.CRYPTOBOT_TOKEN}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://pay.crypt.bot/api/createInvoice",
            headers=headers,
            json=payload,
        )

    if r.status_code >= 400:
        raise RuntimeError(f"CryptoBot error {r.status_code}: {r.text[:500]}")

    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"CryptoBot error: {data}")

    result = data.get("result", {})
    payment.provider_payment_id = str(result.get("invoice_id") or "")
    return result.get("pay_url") or result.get("bot_invoice_url")


async def create_payment(
    s: AsyncSession,
    tg_id: int,
    plan_id: str,
    provider: str,
    promo: str | None = None,
):
    plan = await s.get(Plan, plan_id)
    if not plan or not plan.active:
        raise ValueError("Plan not found")

    provider = (provider or "yookassa").lower()
    if provider not in {"yookassa", "cryptobot", "crypto"}:
        raise ValueError("Unknown payment provider")

    amount, promo_note, promo_obj = await _apply_promo(s, plan.price_rub, promo)

    payment = Payment(
        tg_id=int(tg_id),
        plan_id=plan_id,
        provider=provider,
        amount_rub=amount,
        status="pending",
    )
    s.add(payment)
    await s.flush()

    s.add(
        Log(
            tg_id=int(tg_id),
            action="payment_created_local",
            payload=f"{provider}:{plan_id}:{amount};{promo_note}",
        )
    )
    await s.commit()
    await s.refresh(payment)

    try:
        if provider == "yookassa":
            checkout_url = await _create_yookassa_payment(payment, plan)
        else:
            checkout_url = await _create_cryptobot_invoice(payment, plan)

        if not checkout_url:
            raise RuntimeError("Payment provider did not return checkout URL")

        if promo_obj:
            promo_obj.uses_left -= 1
            if promo_obj.uses_left <= 0:
                promo_obj.active = False

        s.add(
            Log(
                tg_id=int(tg_id),
                action="payment_provider_created",
                payload=f"payment_id={payment.id}",
            )
        )
        await s.commit()
        await s.refresh(payment)
        return payment, checkout_url

    except Exception as e:
        payment.status = "error"
        s.add(Log(tg_id=int(tg_id), action="payment_provider_error", payload=str(e)))
        await s.commit()
        raise


async def mark_payment_paid(
    s: AsyncSession,
    payment: Payment,
    invite_link: str | None = None,
):
    payment.status = "paid"
    payment.paid_at = datetime.utcnow()
    payment.invite_link = invite_link

    s.add(
        Log(
            tg_id=payment.tg_id,
            action="payment_paid",
            payload=f"payment_id={payment.id};invite={invite_link or '-'}",
        )
    )
    await s.commit()
    return payment


async def check_provider_payment_status(payment: Payment) -> str:
    """Return provider status: pending / paid / canceled."""
    provider = (payment.provider or "").lower()

    if provider == "yookassa":
        if (
            not settings.YOOKASSA_SHOP_ID
            or not settings.YOOKASSA_SECRET_KEY
            or not payment.provider_payment_id
        ):
            return payment.status

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"https://api.yookassa.ru/v3/payments/{payment.provider_payment_id}",
                auth=(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY),
            )

        if r.status_code >= 400:
            return payment.status

        data = r.json()
        if data.get("paid") is True or data.get("status") == "succeeded":
            return "paid"
        if data.get("status") in {"canceled"}:
            return "canceled"
        return "pending"

    if provider in {"cryptobot", "crypto"}:
        if not settings.CRYPTOBOT_TOKEN or not payment.provider_payment_id:
            return payment.status

        headers = {"Crypto-Pay-API-Token": settings.CRYPTOBOT_TOKEN}
        params = {"invoice_ids": payment.provider_payment_id}

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                "https://pay.crypt.bot/api/getInvoices",
                headers=headers,
                params=params,
            )

        if r.status_code >= 400:
            return payment.status

        data = r.json()
        if not data.get("ok"):
            return payment.status

        items = data.get("result", {}).get("items", [])
        if not items:
            return payment.status

        status = items[0].get("status")
        if status == "paid":
            return "paid"
        if status in {"expired"}:
            return "canceled"
        return "pending"

    return payment.status
