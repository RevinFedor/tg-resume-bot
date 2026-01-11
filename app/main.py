import asyncio
import logging
import os
import sys

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from aiogram import Bot, Dispatcher
from aiogram.types import Update

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

# Webhook path
WEBHOOK_PATH = "/webhook"


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

    # Запуск scheduler (каждые 30 секунд)
    from app.services.scheduler import set_scheduler
    interval_seconds = int(os.getenv("CHECK_INTERVAL_SECONDS", "30"))
    scheduler = Scheduler(bot, interval_seconds=interval_seconds)
    set_scheduler(scheduler)  # Сохраняем для доступа из команд
    await scheduler.start()

    # Настройка webhook
    WEBHOOK_URL = os.getenv("WEBHOOK_URL") or os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if WEBHOOK_URL:
        if not WEBHOOK_URL.startswith("http"):
            WEBHOOK_URL = f"https://{WEBHOOK_URL}"
        webhook_full_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"

        await bot.set_webhook(
            url=webhook_full_url,
            drop_pending_updates=False,  # Не терять сообщения!
        )
        logger.info(f"Webhook set: {webhook_full_url}")
    else:
        # Fallback на polling если нет URL
        logger.warning("No WEBHOOK_URL, starting polling...")
        polling_task = asyncio.create_task(dp.start_polling(bot))

    yield

    # Остановка
    logger.info("Stopping application...")

    if scheduler:
        await scheduler.stop()

    # Удаляем webhook при остановке
    if WEBHOOK_URL:
        await bot.delete_webhook()

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


@app.post(WEBHOOK_PATH)
async def webhook_handler(request: Request):
    """Обработчик webhook от Telegram"""
    try:
        data = await request.json()

        # Логируем ВСЕ входящие сообщения
        logger.info(f"[WEBHOOK] Received update: {data.get('update_id')}")

        if 'message' in data:
            msg = data['message']
            msg_type = "unknown"
            if msg.get('text'):
                msg_type = "text"
            elif msg.get('voice'):
                msg_type = "voice"
            elif msg.get('video_note'):
                msg_type = "video_note"
            elif msg.get('audio'):
                msg_type = "audio"
            elif msg.get('photo'):
                msg_type = "photo"
            elif msg.get('forward_from_chat'):
                msg_type = "forwarded"

            from_user = msg.get('from', {})
            logger.info(
                f"[WEBHOOK] Message type={msg_type} "
                f"from={from_user.get('id')} "
                f"(@{from_user.get('username', 'no_username')})"
            )

        update = Update(**data)
        await dp.feed_update(bot, update)

    except Exception as e:
        logger.error(f"[WEBHOOK] Error processing update: {e}", exc_info=True)

    return {"ok": True}


@app.get("/")
async def root():
    return {
        "status": "ok",
        "bot": "@chanresume_bot",
        "admin": "/admin",
        "webhook": WEBHOOK_PATH,
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
