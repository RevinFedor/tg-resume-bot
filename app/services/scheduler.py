import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import get_async_session
from app.db.models import Channel, Subscription, Post
from app.services.parser import ChannelParser
from app.services.summarizer import Summarizer
from app.services.userbot import get_userbot_service, AuthState
from app.services.transcription import TranscriptionService

logger = logging.getLogger(__name__)


class Scheduler:
    """Фоновый планировщик для проверки каналов"""

    def __init__(self, bot, interval_seconds: int = 30):
        self.bot = bot
        self.interval_seconds = interval_seconds
        self.parser = ChannelParser()
        self.summarizer = Summarizer()
        self._transcriber: TranscriptionService | None = None
        self._running = False
        self._task: asyncio.Task | None = None

    def _get_transcriber(self) -> TranscriptionService:
        """Ленивая инициализация транскрибера"""
        if self._transcriber is None:
            self._transcriber = TranscriptionService()
        return self._transcriber

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
        # Проверяем доступность userbot
        userbot = get_userbot_service()
        userbot_status = await userbot.get_status()
        userbot_available = userbot_status.get("state") == AuthState.AUTHORIZED

        if userbot_available:
            logger.info("Userbot is available, will use for media parsing")
        else:
            logger.debug("Userbot not available, using web parser only")

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
                    await self._process_channel(session, channel, userbot_available)
                except Exception as e:
                    logger.error(f"Error processing channel @{channel.username}: {e}")

            await session.commit()

    async def _process_channel(self, session, channel: Channel, userbot_available: bool = False):
        """Обрабатывает один канал"""
        # Если userbot доступен, используем его для полного парсинга
        if userbot_available:
            await self._process_channel_with_userbot(session, channel)
        else:
            await self._process_channel_web(session, channel)

    async def _process_channel_web(self, session, channel: Channel):
        """Обрабатывает канал через веб-парсинг (только текст и фото)"""
        posts = await self.parser.get_posts(channel.username, channel.last_post_id)

        if not posts:
            channel.last_checked_at = datetime.utcnow()
            return

        logger.info(f"[WEB] Found {len(posts)} new posts in @{channel.username}")

        for post in posts:
            existing = await session.execute(
                select(Post).where(
                    Post.channel_id == channel.id,
                    Post.post_id == post.post_id
                )
            )
            if existing.scalar_one_or_none():
                continue

            try:
                summary, stats = await self.summarizer.summarize(
                    post.content,
                    channel.username
                )
            except Exception as e:
                logger.error(f"Failed to summarize post {post.post_id}: {e}")
                continue

            db_post = Post(
                channel_id=channel.id,
                post_id=post.post_id,
                content=post.content,
                summary=summary,
            )
            session.add(db_post)

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

        max_post_id = max(p.post_id for p in posts)
        if max_post_id > channel.last_post_id:
            channel.last_post_id = max_post_id

        channel.last_checked_at = datetime.utcnow()

    async def _process_channel_with_userbot(self, session, channel: Channel):
        """Обрабатывает канал через userbot (включая голосовые и кружки)"""
        userbot = get_userbot_service()
        messages = await userbot.get_channel_messages(
            channel.username,
            after_id=channel.last_post_id,
            limit=20
        )

        if not messages:
            channel.last_checked_at = datetime.utcnow()
            return

        logger.info(f"[USERBOT] Found {len(messages)} new messages in @{channel.username}")

        for msg in messages:
            msg_id = msg["id"]

            # Проверяем, не обрабатывали ли уже
            existing = await session.execute(
                select(Post).where(
                    Post.channel_id == channel.id,
                    Post.post_id == msg_id
                )
            )
            if existing.scalar_one_or_none():
                continue

            content = msg.get("text", "")
            media_type = msg.get("media_type", "text")

            # Если это голосовое или кружок - транскрибируем
            if media_type in ("voice", "video_note", "audio"):
                try:
                    media_data = await userbot.download_media(channel.username, msg_id)
                    if media_data:
                        ext = ".ogg" if media_type == "voice" else ".mp4"
                        transcript = await self._get_transcriber().transcribe_bytes(
                            media_data,
                            filename=f"media{ext}"
                        )
                        if transcript:
                            content = f"[{media_type.upper()}] {transcript}"
                            logger.info(f"Transcribed {media_type} from @{channel.username}/{msg_id}")
                except Exception as e:
                    logger.error(f"Failed to transcribe {media_type} from @{channel.username}/{msg_id}: {e}")
                    continue

            # Пропускаем если нет контента
            if not content or len(content.strip()) < 10:
                continue

            # Создаём резюме
            try:
                summary, stats = await self.summarizer.summarize(content, channel.username)
            except Exception as e:
                logger.error(f"Failed to summarize post {msg_id}: {e}")
                continue

            # Сохраняем пост
            db_post = Post(
                channel_id=channel.id,
                post_id=msg_id,
                content=content,
                summary=summary,
            )
            session.add(db_post)

            # Формируем метку для типа контента
            type_label = ""
            if media_type == "voice":
                type_label = " (голосовое)"
            elif media_type == "video_note":
                type_label = " (кружок)"
            elif media_type == "audio":
                type_label = " (аудио)"

            # Отправляем резюме всем подписчикам
            for subscription in channel.subscriptions:
                try:
                    await self._send_summary(
                        subscription.user.telegram_id,
                        channel.username,
                        summary,
                        msg_id,
                        type_label=type_label
                    )
                except Exception as e:
                    logger.error(f"Failed to send to user {subscription.user.telegram_id}: {e}")

        # Обновляем last_post_id
        if messages:
            max_post_id = max(m["id"] for m in messages)
            if max_post_id > channel.last_post_id:
                channel.last_post_id = max_post_id

        channel.last_checked_at = datetime.utcnow()

    async def _send_summary(
        self,
        telegram_id: int,
        channel: str,
        summary: str,
        post_id: int,
        type_label: str = ""
    ):
        """Отправляет резюме пользователю"""
        import telegramify_markdown
        from telegramify_markdown import customize
        from aiogram.enums import ParseMode

        customize.strict_markdown = False

        # Добавляем метку типа контента если есть
        header = f"**@{channel}**{type_label}"
        message = f"{header}\n\n{summary}\n\n[Открыть пост в @{channel} →](https://t.me/{channel}/{post_id})"

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
            plain_message = f"@{channel}{type_label}\n\n{summary}\n\nОткрыть пост: https://t.me/{channel}/{post_id}"
            await self.bot.send_message(telegram_id, plain_message)
