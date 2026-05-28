import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .config import settings
from .db import init_db
from .api.routes import router as api_router
from .bot.handlers import router as bot_router
from .services.kicker import kick_expired
from .services.payment_checker import check_pending_payments

app = FastAPI(title="All of Naive XP Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)

bot = Bot(settings.BOT_TOKEN)
dp = Dispatcher()
dp.include_router(bot_router)
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup():
    await init_db()
    scheduler.add_job(kick_expired, "interval", minutes=10, args=[bot])
    scheduler.add_job(check_pending_payments, "interval", minutes=1, args=[bot])
    scheduler.start()
    asyncio.create_task(dp.start_polling(bot))

@app.get("/")
async def root():
    return {"status": "all_of_naive.exe running"}
