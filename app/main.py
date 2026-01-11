import asyncio
import logging
import os
import sys

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from aiogram import Bot, Dispatcher

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Глобальные переменные (инициализируются в lifespan)
bot: Bot | None = None
dp: Dispatcher | None = None
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle события FastAPI"""
    global bot, dp, scheduler

    logger.info("Starting application...")

    # Импортируем здесь чтобы избежать проблем с env variables
    from app.db.database import get_engine, init_db
    from app.bot.handlers import setup_handlers
    from app.services.scheduler import Scheduler
    from app.admin import setup_admin

    # Проверяем токены
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        raise ValueError("BOT_TOKEN not set")

    # Инициализация бота
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Инициализация БД
    await init_db()
    logger.info("Database initialized")

    # Настройка админки (после инициализации БД)
    setup_admin(app, get_engine())
    logger.info("Admin panel initialized")

    # Настройка хендлеров бота
    setup_handlers(dp)

    # Запуск scheduler
    interval = int(os.getenv("CHECK_INTERVAL_MINUTES", "5"))
    scheduler = Scheduler(bot, interval_minutes=interval)
    await scheduler.start()

    # Запуск polling в фоне
    polling_task = asyncio.create_task(dp.start_polling(bot))
    logger.info("Bot polling started")

    yield

    # Остановка
    logger.info("Stopping application...")

    if scheduler:
        await scheduler.stop()

    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    await bot.session.close()
    logger.info("Application stopped")


# FastAPI приложение
app = FastAPI(
    title="Channel Resume Bot",
    description="Telegram bot for channel digests",
    lifespan=lifespan,
)

# Middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "default-secret-key"),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API роуты импортируем лениво
from app.api import router as api_router
app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "bot": "@chanresume_bot",
        "admin": "/admin",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False,
    )
