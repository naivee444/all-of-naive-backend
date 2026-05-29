import hmac
import hashlib
import json
from urllib.parse import parse_qsl

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from ..config import settings
from ..db import Log, Payment, Plan, PromoCode, Setting, Subscription, User, SessionLocal
from ..services.payment_checker import confirm_payment_if_paid
from ..services.payments import create_payment
from ..services.users import upsert_user


router = APIRouter(prefix="/api")


class InitData(BaseModel):
    initData: str


class CreatePaymentReq(BaseModel):
    initData: str
    plan_id: str
    provider: str
    promo: str | None = None
    accepted_legal: bool = False


class MockPaidReq(BaseModel):
    payment_id: int


def validate_init_data(init_data: str) -> dict:
    parsed = dict(parse_qsl(init_data or "", keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Missing Telegram hash")

    data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(
        b"WebAppData",
        settings.BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()
    calculated = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        raise HTTPException(401, "Bad Telegram initData")

    user = json.loads(parsed.get("user", "{}"))
    if not user.get("id"):
        raise HTTPException(401, "No Telegram user")

    return user


@router.get("/health")
async def health():
    return {"ok": True, "service": "all_of_naive_backend"}


@router.get("/plans")
async def plans():
    async with SessionLocal() as s:
        result = await s.execute(select(Plan).where(Plan.active == True))
        return [
            {
                "id": p.id,
                "title_ru": p.title_ru,
                "title_uk": p.title_uk,
                "days": p.days,
                "price_rub": p.price_rub,
            }
            for p in result.scalars().all()
        ]


@router.post("/profile")
async def profile(req: InitData):
    user_data = validate_init_data(req.initData)
    tg_id = int(user_data["id"])

    async with SessionLocal() as s:
        user = await upsert_user(
            s,
            tg_id=tg_id,
            username=user_data.get("username"),
            first_name=user_data.get("first_name"),
            language=user_data.get("language_code") or "ru",
        )

        sub = (
            await s.execute(
                select(Subscription)
                .where(Subscription.tg_id == tg_id, Subscription.active == True)
                .order_by(Subscription.expires_at.desc())
            )
        ).scalars().first()
        plan = await s.get(Plan, sub.plan_id) if sub else None

        return {
            "tg_id": tg_id,
            "username": user_data.get("username") or (user.username if user else None),
            "first_name": user_data.get("first_name") or (user.first_name if user else None),
            "photo_url": user_data.get("photo_url"),
            "subscription": None
            if not sub
            else {
                "plan_id": sub.plan_id,
                "plan_title": plan.title_ru if plan else sub.plan_id,
                "expires_at": sub.expires_at.isoformat(),
                "active": sub.active,
            },
        }


@router.post("/payments/create")
async def payments_create(req: CreatePaymentReq):
    if not req.accepted_legal:
        raise HTTPException(400, "Offer acceptance required")

    user_data = validate_init_data(req.initData)
    tg_id = int(user_data["id"])

    async with SessionLocal() as s:
        await upsert_user(
            s,
            tg_id=tg_id,
            username=user_data.get("username"),
            first_name=user_data.get("first_name"),
            language=user_data.get("language_code") or "ru",
        )

        try:
            payment, url = await create_payment(
                s,
                tg_id=tg_id,
                plan_id=req.plan_id,
                provider=req.provider,
                promo=req.promo,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        except RuntimeError as e:
            raise HTTPException(502, str(e))
        except Exception as e:
            raise HTTPException(500, f"Payment create failed: {e}")

    bot = Bot(settings.BOT_TOKEN)
    try:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="оплатить.exe", url=url)]]
        )
        await bot.send_message(
            tg_id,
            (
                "payment_created.exe\n\n"
                f"ID платежа: {payment.id}\n"
                f"Сумма: {payment.amount_rub} ₽\n"
                f"Способ: {req.provider}\n\n"
                "Нажми кнопку ниже для оплаты. После успешной оплаты бот выдаст invite-ссылку."
            ),
            reply_markup=kb,
        )
    except Exception:
        pass
    finally:
        await bot.session.close()

    return {
        "ok": True,
        "payment_id": payment.id,
        "checkout_url": url,
        "status": payment.status,
    }


@router.post("/payments/mock-paid")
async def mock_paid(req: MockPaidReq):
    bot = Bot(settings.BOT_TOKEN)
    try:
        ok = await confirm_payment_if_paid(bot, req.payment_id)
        return {"ok": ok}
    finally:
        await bot.session.close()


@router.post("/webhooks/yookassa")
async def yookassa_webhook(request: Request):
    data = await request.json()
    payment_id = data.get("object", {}).get("metadata", {}).get("payment_id")
    if not payment_id:
        return {"ok": True}

    bot = Bot(settings.BOT_TOKEN)
    try:
        await confirm_payment_if_paid(bot, int(payment_id))
    finally:
        await bot.session.close()

    return {"ok": True}


@router.post("/webhooks/cryptobot")
async def cryptobot_webhook(request: Request):
    data = await request.json()
    payload = (
        data.get("payload")
        or data.get("update", {}).get("payload")
        or data.get("result", {}).get("payload")
    )
    if not payload:
        return {"ok": True}

    bot = Bot(settings.BOT_TOKEN)
    try:
        await confirm_payment_if_paid(bot, int(payload))
    finally:
        await bot.session.close()

    return {"ok": True}


@router.get("/trial")
async def trial():
    async with SessionLocal() as s:
        setting = await s.get(Setting, "trial_link")
        return {"trial_link": setting.value if setting else ""}


@router.get("/promo/check")
async def promo_check(code: str):
    code = (code or "").strip().upper()
    if not code:
        return {"ok": False, "reason": "empty"}

    async with SessionLocal() as s:
        promo = await s.get(PromoCode, code)
        if not promo or not promo.active or promo.uses_left <= 0:
            return {"ok": False, "reason": "not_found"}

        return {
            "ok": True,
            "code": promo.code,
            "discount_percent": promo.discount_percent,
            "uses_left": promo.uses_left,
        }
