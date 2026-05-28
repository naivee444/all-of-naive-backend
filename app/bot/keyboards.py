from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from ..config import settings


def start_kb():
    # Telegram не позволяет менять цвет inline/webapp-кнопок. Цвет задается клиентом Telegram.
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="запустить.exe", web_app=WebAppInfo(url=settings.WEBAPP_URL))]])


def admin_kb():
    rows = [
        [("Пользователи", "admin_users"), ("Тарифы", "admin_plans")],
        [("Промокоды", "admin_promos"), ("Выдать подписку", "admin_grant")],
        [("Trial-ссылка", "admin_trial"), ("Рассылка всем", "admin_broadcast")],
        [("Логи", "admin_logs"), ("RU / UA", "admin_langs")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])
