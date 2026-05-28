from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .config import settings

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="ru")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title_ru: Mapped[str] = mapped_column(String(64))
    title_uk: Mapped[str] = mapped_column(String(64))
    days: Mapped[int] = mapped_column(Integer)
    price_rub: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    plan_id: Mapped[str] = mapped_column(String(32))
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    plan_id: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    provider_payment_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    amount_rub: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    invite_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class PromoCode(Base):
    __tablename__ = "promo_codes"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    uses_left: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

class Log(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(128))
    payload: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

engine = create_async_engine(settings.DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        for plan in [
            Plan(id="m1", title_ru="1 месяц", title_uk="1 місяць", days=30, price_rub=2790),
            Plan(id="m3", title_ru="3 месяца", title_uk="3 місяці", days=90, price_rub=6990),
            Plan(id="m6", title_ru="6 месяцев", title_uk="6 місяців", days=180, price_rub=11990),
            Plan(id="forever", title_ru="Навсегда (10 лет)", title_uk="Назавжди (10 років)", days=3650, price_rub=14990),
        ]:
            if not await s.get(Plan, plan.id):
                s.add(plan)
        if not await s.get(Setting, "trial_link"):
            s.add(Setting(key="trial_link", value=settings.TRIAL_CHANNEL_LINK))
        await s.commit()
