import json
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from ..db import SessionLocal, User, Plan, Log, Setting, PromoCode, Payment, Subscription
from ..config import settings
from ..services.users import upsert_user
from ..services.subscriptions import grant_subscription
from ..services.payments import create_payment, mark_payment_paid
from ..services.invites import create_one_time_invite
from .keyboards import start_kb, admin_kb

router = Router()

WELCOME = (
    "All Of Naive — закрытый курс по монтажу.\n\n"
    "Внутри: туториалы, разборы работ, плагины, AE-файлы, музыка, полезные материалы "
    "и доступ к закрытому комьюнити."
)


def _parse_start_buy_args(args: str) -> tuple[str, str, str | None]:
    # Expected patterns:
    # buy_m1_yookassa
    # buy_m1_yookassa_promo_CODE
    promo = None
    if "_promo_" in args:
        base, promo = args.split("_promo_", 1)
    else:
        base = args
    parts = base.split("_")
    plan_id = parts[1] if len(parts) > 1 else "m1"
    provider = parts[2] if len(parts) > 2 else "yookassa"
    return plan_id, provider, promo or None


async def validate_promo_code(s, promo: str | None):
    if not promo:
        return None
    code = promo.strip().upper()
    promo_obj = await s.get(PromoCode, code)
    if not promo_obj or not promo_obj.active or promo_obj.uses_left <= 0:
        return False
    return promo_obj


async def is_admin(user_id: int) -> bool:
    return user_id == settings.ADMIN_TELEGRAM_ID


@router.message(CommandStart())
async def start(message: Message, command: CommandObject = None):
    args = (command.args or "").strip() if command else ""
    async with SessionLocal() as s:
        await upsert_user(s, message.from_user.id, message.from_user.username, message.from_user.first_name)
        s.add(Log(tg_id=message.from_user.id, action="start", payload=args))
        await s.commit()

    if args == "trial":
        async with SessionLocal() as s:
            setting = await s.get(Setting, "trial_link")
        if setting and setting.value:
            return await message.answer(f"trial_link.exe\n\n{setting.value}")
        return await message.answer("Trial-ссылка пока не задана. Админ может добавить её через /set_trial <ссылка>")

    if args.startswith("buy_"):
        plan_id, provider, promo = _parse_start_buy_args(args)
        try:
            async with SessionLocal() as s:
                promo_obj = await validate_promo_code(s, promo)
                if promo and promo_obj is False:
                    return await message.answer(
                        "promo_error.exe\n\nТакого промокода нет, он отключен или уже закончился."
                    )
                payment, url = await create_payment(s, message.from_user.id, plan_id, provider, promo=promo)
                promo_line = ""
                if promo_obj:
                    promo_line = f"Промокод: {promo_obj.code} (-{promo_obj.discount_percent}%)\n"
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="оплатить.exe", url=url)]])
            return await message.answer(
                f"payment_created.exe\n\n"
                f"ID платежа: {payment.id}\n"
                f"Сумма: {payment.amount_rub} ₽\n"
                f"Способ: {provider}\n"
                f"{promo_line}\n"
                f"После оплаты бот выдаст персональную invite-ссылку.",
                reply_markup=kb,
            )
        except Exception as e:
            return await message.answer(f"payment_error.exe\n\n{e}")

    photo = FSInputFile("../frontend/src/assets/banner.jpg")
    try:
        await message.answer_photo(photo=photo, caption=WELCOME, reply_markup=start_kb())
    except Exception:
        await message.answer(WELCOME, reply_markup=start_kb())


@router.message(F.web_app_data)
async def web_app_data(message: Message, bot: Bot):
    try:
        data = json.loads(message.web_app_data.data or "{}")
    except Exception:
        return await message.answer("Ошибка данных mini_app.exe")
    action = data.get("action")
    async with SessionLocal() as s:
        await upsert_user(s, message.from_user.id, message.from_user.username, message.from_user.first_name)
        s.add(Log(tg_id=message.from_user.id, action=f"webapp_{action}", payload=json.dumps(data, ensure_ascii=False)))
        await s.commit()

    if action == "trial":
        async with SessionLocal() as s:
            setting = await s.get(Setting, "trial_link")
        if setting and setting.value:
            return await message.answer(f"trial_link.exe\n\n{setting.value}")
        return await message.answer("Trial-ссылка пока не задана. Админ может добавить её через /set_trial <ссылка>")

    if action == "check_promo":
        promo = (data.get("promo") or "").strip()
        if not promo:
            return await message.answer("promo_error.exe\n\nВведи промокод перед проверкой.")
        async with SessionLocal() as s:
            promo_obj = await validate_promo_code(s, promo)
        if promo_obj is False:
            return await message.answer("promo_error.exe\n\nТакого промокода нет, он отключен или уже закончился.")
        return await message.answer(
            f"promo_ok.exe\n\nПромокод {promo_obj.code} активен. Скидка: {promo_obj.discount_percent}%. Осталось использований: {promo_obj.uses_left}."
        )

    if action == "buy":
        plan_id = data.get("plan_id", "m1")
        provider = data.get("provider", "yookassa")
        promo = data.get("promo") or None
        try:
            async with SessionLocal() as s:
                promo_obj = await validate_promo_code(s, promo)
                if promo and promo_obj is False:
                    return await message.answer(
                        "promo_error.exe\n\nТакого промокода нет, он отключен или уже закончился."
                    )
                payment, url = await create_payment(s, message.from_user.id, plan_id, provider, promo=promo)
                promo_line = ""
                if promo_obj:
                    promo_line = f"Промокод: {promo_obj.code} (-{promo_obj.discount_percent}%)\n"
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="оплатить.exe", url=url)]])
            await message.answer(
                f"payment_created.exe\n\n"
                f"ID платежа: {payment.id}\n"
                f"Сумма: {payment.amount_rub} ₽\n"
                f"Способ: {provider}\n"
                f"{promo_line}\n"
                f"Нажми кнопку ниже, чтобы перейти к оплате.",
                reply_markup=kb,
            )
        except Exception as e:
            await message.answer(f"payment_error.exe\n\n{e}")
        return

    if action == "profile":
        async with SessionLocal() as s:
            sub = (await s.execute(select(Subscription).where(Subscription.tg_id == message.from_user.id, Subscription.active == True).order_by(Subscription.expires_at.desc()))).scalars().first()
            if not sub:
                return await message.answer("profile.exe\n\nПодписка: у вас нет активной подписки\nСтатус: не бро")
            plan = await s.get(Plan, sub.plan_id)
            return await message.answer(f"profile.exe\n\nПодписка: {(plan.title_ru if plan else sub.plan_id)}\nДействует до: {sub.expires_at:%d.%m.%Y %H:%M}\nСтатус: мой бро")

    await message.answer("Неизвестная команда mini_app.exe")


@router.message(Command("profile"))
async def profile_cmd(message: Message):
    async with SessionLocal() as s:
        sub = (await s.execute(select(Subscription).where(Subscription.tg_id == message.from_user.id, Subscription.active == True).order_by(Subscription.expires_at.desc()))).scalars().first()
        if not sub:
            return await message.answer("profile.exe\n\nПодписка: у вас нет активной подписки\nСтатус: не бро")
        plan = await s.get(Plan, sub.plan_id)
        return await message.answer(f"profile.exe\n\nПодписка: {(plan.title_ru if plan else sub.plan_id)}\nДействует до: {sub.expires_at:%d.%m.%Y %H:%M}\nСтатус: мой бро")


@router.message(Command("admin"))
async def admin(message: Message):
    if not await is_admin(message.from_user.id):
        return await message.answer("access_denied.exe")
    await message.answer("Админ-панель.exe", reply_markup=admin_kb())


@router.callback_query(F.data == "admin_users")
async def admin_users(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return await cb.answer("Нет доступа")
    async with SessionLocal() as s:
        users = (await s.execute(select(User).order_by(User.created_at.desc()).limit(15))).scalars().all()
    text = "Последние пользователи:\n" + "\n".join([f"{u.tg_id} @{u.username or '-'} | {u.first_name or '-'}" for u in users])
    await cb.message.answer(text or "Пока нет пользователей", reply_markup=admin_kb())


@router.callback_query(F.data == "admin_plans")
async def admin_plans(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return await cb.answer("Нет доступа")
    async with SessionLocal() as s:
        plans = (await s.execute(select(Plan))).scalars().all()
    text = "Тарифы:\n" + "\n".join([f"{p.id}: {p.title_ru} — {p.price_rub} ₽ / {p.days} дн. | {'on' if p.active else 'off'}" for p in plans])
    text += "\n\nИзменить цену: /set_price <id> <цена>\nНапример: /set_price m1 2990"
    await cb.message.answer(text, reply_markup=admin_kb())


@router.message(Command("set_price"))
async def set_price(message: Message):
    if not await is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("Формат: /set_price <m1|m3|m6|forever> <цена>")
    plan_id, price = parts[1], int(parts[2])
    async with SessionLocal() as s:
        plan = await s.get(Plan, plan_id)
        if not plan: return await message.answer("Тариф не найден")
        plan.price_rub = price
        s.add(Log(tg_id=message.from_user.id, action="price_changed", payload=f"{plan_id}={price}"))
        await s.commit()
    await message.answer(f"Цена обновлена: {plan_id} = {price} ₽")


@router.callback_query(F.data == "admin_promos")
async def admin_promos(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return await cb.answer("Нет доступа")
    async with SessionLocal() as s:
        promos = (await s.execute(select(PromoCode).limit(20))).scalars().all()
    text = "Промокоды:\n" + ("\n".join([f"{p.code}: -{p.discount_percent}% | осталось {p.uses_left} | {'on' if p.active else 'off'}" for p in promos]) or "пока нет")
    text += "\n\nСоздать: /promo <CODE> <скидка_%> <кол-во>\nУдалить: /delpromo <CODE>"
    await cb.message.answer(text, reply_markup=admin_kb())


@router.message(Command("promo"))
async def promo(message: Message):
    if not await is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) != 4:
        return await message.answer("Формат: /promo <CODE> <скидка_%> <кол-во>")
    code, discount, uses = parts[1].upper(), int(parts[2]), int(parts[3])
    async with SessionLocal() as s:
        p = await s.get(PromoCode, code) or PromoCode(code=code)
        p.discount_percent = max(0, min(100, discount)); p.uses_left = uses; p.active = True
        s.add(p); s.add(Log(tg_id=message.from_user.id, action="promo_saved", payload=f"{code}:{discount}:{uses}"))
        await s.commit()
    await message.answer(f"Промокод сохранен: {code}")


@router.message(Command("delpromo"))
async def delpromo(message: Message):
    if not await is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) != 2: return await message.answer("Формат: /delpromo <CODE>")
    async with SessionLocal() as s:
        p = await s.get(PromoCode, parts[1].upper())
        if p: p.active = False
        await s.commit()
    await message.answer("Промокод отключен")


@router.callback_query(F.data == "admin_trial")
async def admin_trial(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return await cb.answer("Нет доступа")
    async with SessionLocal() as s:
        setting = await s.get(Setting, "trial_link")
    await cb.message.answer(f"Текущая trial-ссылка:\n{setting.value if setting else 'не задана'}\n\nИзменить: /set_trial <ссылка>", reply_markup=admin_kb())


@router.message(Command("set_trial"))
async def set_trial(message: Message):
    if not await is_admin(message.from_user.id): return
    link = message.text.replace("/set_trial", "", 1).strip()
    if not link: return await message.answer("Формат: /set_trial https://t.me/+...")
    async with SessionLocal() as s:
        setting = await s.get(Setting, "trial_link")
        if not setting:
            setting = Setting(key="trial_link", value=link); s.add(setting)
        setting.value = link
        s.add(Log(tg_id=message.from_user.id, action="trial_link_changed", payload=link))
        await s.commit()
    await message.answer("trial-ссылка обновлена.exe")


@router.callback_query(F.data == "admin_logs")
async def admin_logs(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return await cb.answer("Нет доступа")
    async with SessionLocal() as s:
        logs = (await s.execute(select(Log).order_by(Log.created_at.desc()).limit(20))).scalars().all()
    text = "Логи:\n" + "\n".join([f"{l.created_at:%d.%m %H:%M} | {l.tg_id or '-'} | {l.action}" for l in logs])
    await cb.message.answer(text or "Логи пустые", reply_markup=admin_kb())


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return await cb.answer("Нет доступа")
    await cb.message.answer("Рассылка всем:\n/broadcast текст поста", reply_markup=admin_kb())


@router.message(Command("broadcast"))
async def broadcast(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id): return
    text = message.text.replace("/broadcast", "", 1).strip()
    if not text: return await message.answer("Формат: /broadcast текст")
    sent = 0
    async with SessionLocal() as s:
        users = (await s.execute(select(User))).scalars().all()
        for u in users:
            try:
                await bot.send_message(u.tg_id, text)
                sent += 1
            except Exception as e:
                s.add(Log(tg_id=u.tg_id, action="broadcast_error", payload=str(e)))
        s.add(Log(tg_id=message.from_user.id, action="broadcast_sent", payload=f"sent={sent}"))
        await s.commit()
    await message.answer(f"Рассылка завершена. Отправлено: {sent}")


@router.callback_query(F.data == "admin_grant")
async def admin_grant(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return await cb.answer("Нет доступа")
    await cb.message.answer("Выдать подписку:\n/grant <telegram_id> <m1|m3|m6|forever>", reply_markup=admin_kb())


@router.message(Command("grant"))
async def grant(message: Message):
    if not await is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("Формат: /grant <telegram_id> <m1|m3|m6|forever>")
    async with SessionLocal() as s:
        sub = await grant_subscription(s, int(parts[1]), parts[2])
    await message.answer(f"Выдано до {sub.expires_at:%d.%m.%Y %H:%M}")


@router.message(Command("payments"))
async def payments(message: Message):
    if not await is_admin(message.from_user.id): return
    async with SessionLocal() as s:
        rows = (await s.execute(select(Payment).order_by(Payment.created_at.desc()).limit(20))).scalars().all()
    text = "Платежи:\n" + ("\n".join([f"#{p.id} | {p.tg_id} | {p.plan_id} | {p.amount_rub} ₽ | {p.provider} | {p.status}" for p in rows]) or "пока нет")
    text += "\n\nРучное подтверждение теста: /paid <payment_id>"
    await message.answer(text)


@router.message(Command("paid"))
async def paid(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) != 2: return await message.answer("Формат: /paid <payment_id>")
    async with SessionLocal() as s:
        payment = await s.get(Payment, int(parts[1]))
        if not payment: return await message.answer("Платеж не найден")
        invite = await create_one_time_invite(bot, payment.tg_id)
        await mark_payment_paid(s, payment, invite)
        sub = await grant_subscription(s, payment.tg_id, payment.plan_id)
    await bot.send_message(payment.tg_id, f"Оплата подтверждена.exe\n\nТвоя одноразовая ссылка в Naive PRIVATE:\n{invite}\n\nЗаявку проверит владелец.")
    await message.answer(f"Платеж #{payment.id} подтвержден. Подписка до {sub.expires_at:%d.%m.%Y %H:%M}")


@router.callback_query(F.data == "admin_langs")
async def admin_langs(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id): return await cb.answer("Нет доступа")
    await cb.message.answer("RU/UA уже есть в Mini App. Позже добавим редактирование текстов из админки.", reply_markup=admin_kb())
