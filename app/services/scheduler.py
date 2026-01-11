import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import get_async_session
from app.db.models import Channel, Subscription, Post
from app.services.parser import ChannelParser
from app.services.summarizer import Summarizer

logger = logging.getLogger(__name__)


class Scheduler:
    """Фоновый планировщик для проверки каналов"""

    def __init__(self, bot, interval_minutes: int = 5):
        self.bot = bot
        self.interval_seconds = interval_minutes * 60
        self.parser = ChannelParser()
        self.summarizer = Summarizer()
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """Запускает scheduler"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Scheduler started (interval: {self.interval_seconds}s)")

    async def stop(self):
        """Останавливает scheduler"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.parser.close()
        logger.info("Scheduler stopped")

    async def _run_loop(self):
        """Основной цикл проверки"""
        while self._running:
            try:
                await self._check_channels()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            await asyncio.sleep(self.interval_seconds)

    async def _check_channels(self):
        """Проверяет все активные каналы на новые посты"""
        async with get_async_session()() as session:
            # Получаем все активные каналы с подписками
            result = await session.execute(
                select(Channel)
                .where(Channel.is_active == True)
                .options(selectinload(Channel.subscriptions).selectinload(Subscription.user))
            )
            channels = result.scalars().all()

            if not channels:
                logger.debug("No active channels to check")
                return

            logger.info(f"Checking {len(channels)} channels...")

            for channel in channels:
                try:
                    await self._process_channel(session, channel)
                except Exception as e:
                    logger.error(f"Error processing channel @{channel.username}: {e}")

            await session.commit()

    async def _process_channel(self, session, channel: Channel):
        """Обрабатывает один канал"""
        # Получаем новые посты
        posts = await self.parser.get_posts(channel.username, channel.last_post_id)

        if not posts:
            channel.last_checked_at = datetime.utcnow()
            return

        logger.info(f"Found {len(posts)} new posts in @{channel.username}")

        # Обрабатываем каждый пост
        for post in posts:
            # Проверяем, не обрабатывали ли уже
            existing = await session.execute(
                select(Post).where(
                    Post.channel_id == channel.id,
                    Post.post_id == post.post_id
                )
            )
            if existing.scalar_one_or_none():
                continue

            # Создаём резюме
            try:
                summary, stats = await self.summarizer.summarize(
                    post.content,
                    channel.username
                )
            except Exception as e:
                logger.error(f"Failed to summarize post {post.post_id}: {e}")
                continue

            # Сохраняем пост
            db_post = Post(
                channel_id=channel.id,
                post_id=post.post_id,
                content=post.content,
                summary=summary,
            )
            session.add(db_post)

            # Отправляем резюме всем подписчикам
            for subscription in channel.subscriptions:
                try:
                    await self._send_summary(
                        subscription.user.telegram_id,
                        channel.username,
                        summary,
                        post.post_id
                    )
                except Exception as e:
                    logger.error(f"Failed to send to user {subscription.user.telegram_id}: {e}")

        # Обновляем last_post_id
        max_post_id = max(p.post_id for p in posts)
        if max_post_id > channel.last_post_id:
            channel.last_post_id = max_post_id

        channel.last_checked_at = datetime.utcnow()

    async def _send_summary(self, telegram_id: int, channel: str, summary: str, post_id: int):
        """Отправляет резюме пользователю"""
        import telegramify_markdown
        from telegramify_markdown import customize
        from aiogram.enums import ParseMode

        customize.strict_markdown = False

        message = f"**@{channel}**\n\n{summary}\n\n[Открыть пост в @{channel} →](https://t.me/{channel}/{post_id})"

        try:
            formatted = telegramify_markdown.markdownify(message)
            await self.bot.send_message(
                telegram_id,
                formatted,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True
            )
        except Exception as e:
            # Fallback без форматирования
            logger.warning(f"Markdown formatting failed, sending plain text: {e}")
            plain_message = f"@{channel}\n\n{summary}\n\nОткрыть пост: https://t.me/{channel}/{post_id}"
            await self.bot.send_message(telegram_id, plain_message)
