from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_TELEGRAM_ID: int
    PRIVATE_GROUP_ID: int
    TRIAL_CHANNEL_LINK: str = ""
    WEBAPP_URL: str

    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    CRYPTOBOT_TOKEN: str = ""

    DATABASE_URL: str = "sqlite+aiosqlite:///./all_of_naive.db"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
