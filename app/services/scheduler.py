import asyncio
import logging
import random
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

# Глобальный экземпляр scheduler
_scheduler_instance = None


def get_scheduler():
    """Возвращает экземпляр Scheduler"""
    return _scheduler_instance


def set_scheduler(scheduler):
    """Устанавливает глобальный экземпляр Scheduler"""
    global _scheduler_instance
    _scheduler_instance = scheduler


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

            # Рандомизация интервала ±30% для избежания детекции паттернов
            # Например: 30 сек становится 21-39 сек
            jitter = random.uniform(0.7, 1.3)
            sleep_time = self.interval_seconds * jitter
            logger.debug(f"Next check in {sleep_time:.1f}s (base: {self.interval_seconds}s)")
            await asyncio.sleep(sleep_time)

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
            # Получаем только каналы С ПОДПИСКАМИ (не пустые)
            from app.db.models import Subscription
            result = await session.execute(
                select(Channel)
                .where(Channel.is_active == True)
                .where(Channel.subscriptions.any())  # Только каналы с подписками
                .options(selectinload(Channel.subscriptions).selectinload(Subscription.user))
            )
            channels = result.scalars().all()

            if not channels:
                logger.debug("No channels with subscriptions to check")
                return

            logger.info(f"Checking {len(channels)} channels...")

            for i, channel in enumerate(channels):
                try:
                    await self._process_channel(session, channel, userbot_available)
                except Exception as e:
                    logger.error(f"Error processing channel @{channel.username}: {e}")

                # Случайная задержка между каналами (1-3 сек) для имитации человека
                if i < len(channels) - 1:
                    delay = random.uniform(1.0, 3.0)
                    await asyncio.sleep(delay)

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
                # Задержка для Gemini rate limit (15 RPM)
                await asyncio.sleep(5)
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
                        post.post_id,
                        user_interests=subscription.user.interests
                    )
                except Exception as e:
                    logger.error(f"Failed to send to user {subscription.user.telegram_id}: {e}")

        max_post_id = max(p.post_id for p in posts)
        if max_post_id > channel.last_post_id:
            channel.last_post_id = max_post_id

        channel.last_checked_at = datetime.utcnow()

    async def _process_channel_with_userbot(self, session, channel: Channel):
        """Обрабатывает канал через userbot (включая голосовые, кружки, видео и фото)"""
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

        # Группируем сообщения по media_group_id для обработки альбомов
        grouped_messages = self._group_messages_by_album(messages)

        for group_key, group_msgs in grouped_messages.items():
            try:
                await self._process_message_group(
                    session, channel, userbot, group_msgs
                )
            except Exception as e:
                logger.error(f"Error processing message group in @{channel.username}: {e}")

        # Обновляем last_post_id
        if messages:
            max_post_id = max(m["id"] for m in messages)
            if max_post_id > channel.last_post_id:
                channel.last_post_id = max_post_id

        channel.last_checked_at = datetime.utcnow()

    def _group_messages_by_album(self, messages: list[dict]) -> dict[str, list[dict]]:
        """
        Группирует сообщения по media_group_id.
        Одиночные сообщения получают уникальный ключ.
        """
        groups = {}
        for msg in messages:
            group_id = msg.get("media_group_id")
            if group_id:
                key = f"album_{group_id}"
            else:
                key = f"single_{msg['id']}"

            if key not in groups:
                groups[key] = []
            groups[key].append(msg)

        return groups

    async def _process_message_group(
        self,
        session,
        channel: Channel,
        userbot,
        messages: list[dict]
    ):
        """
        Обрабатывает группу сообщений (альбом или одиночное сообщение).
        """
        # Берём первое сообщение как основное (для ID и текста)
        primary_msg = messages[0]
        msg_id = primary_msg["id"]

        # Проверяем, не обрабатывали ли уже
        existing = await session.execute(
            select(Post).where(
                Post.channel_id == channel.id,
                Post.post_id == msg_id
            )
        )
        if existing.scalar_one_or_none():
            return

        # Собираем весь контент из группы
        text_content = ""
        audio_transcript = ""
        images = []
        content_types = set()

        for msg in messages:
            # Текст (берём из первого сообщения с текстом)
            msg_text = msg.get("text", "")
            if msg_text and not text_content:
                text_content = msg_text
                content_types.add("text")

            media_type = msg.get("media_type", "text")
            all_media = msg.get("all_media_types", [])

            # Обрабатываем аудио-контент (голосовые, кружки, аудио, видео)
            if media_type in ("voice", "video_note", "audio", "video"):
                try:
                    media_data = await userbot.download_media(channel.username, msg["id"])
                    if media_data:
                        ext = ".ogg" if media_type == "voice" else ".mp4"
                        transcript = await self._get_transcriber().transcribe_bytes(
                            media_data,
                            filename=f"media{ext}"
                        )
                        if transcript:
                            audio_transcript += f"\n{transcript}" if audio_transcript else transcript
                            content_types.add(media_type)
                            logger.info(f"Transcribed {media_type} from @{channel.username}/{msg['id']}")
                except Exception as e:
                    logger.error(f"Failed to transcribe {media_type} from @{channel.username}/{msg['id']}: {e}")

            # Обрабатываем фото
            if "photo" in all_media or media_type == "photo":
                try:
                    photo_data = await userbot.download_photo(channel.username, msg["id"])
                    if photo_data:
                        images.append(photo_data)
                        content_types.add("photo")
                        logger.info(f"Downloaded photo from @{channel.username}/{msg['id']}")
                except Exception as e:
                    logger.error(f"Failed to download photo from @{channel.username}/{msg['id']}: {e}")

        # Проверяем есть ли что суммаризировать
        has_content = text_content or audio_transcript or images
        if not has_content:
            logger.debug(f"Skipping empty message group {msg_id} in @{channel.username}")
            return

        # Создаём мультимодальное резюме
        try:
            summary, stats = await self.summarizer.summarize_multimodal(
                text=text_content,
                images=images,
                audio_transcript=audio_transcript,
                channel_name=channel.username,
                content_types=list(content_types)
            )
            # Задержка для rate limit
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Failed to summarize post {msg_id}: {e}")
            return

        # Формируем полный контент для сохранения
        full_content = text_content
        if audio_transcript:
            full_content += f"\n\n[ТРАНСКРИПЦИЯ]\n{audio_transcript}"
        if images:
            full_content += f"\n\n[ФОТО: {len(images)} шт]"

        # Сохраняем пост
        db_post = Post(
            channel_id=channel.id,
            post_id=msg_id,
            content=full_content,
            summary=summary,
        )
        session.add(db_post)

        # Отправляем резюме всем подписчикам (без type_label, т.к. он уже в summary)
        for subscription in channel.subscriptions:
            try:
                await self._send_summary(
                    subscription.user.telegram_id,
                    channel.username,
                    summary,
                    msg_id,
                    user_interests=subscription.user.interests
                )
            except Exception as e:
                logger.error(f"Failed to send to user {subscription.user.telegram_id}: {e}")

    async def _send_summary(
        self,
        telegram_id: int,
        channel: str,
        summary: str,
        post_id: int,
        type_label: str = "",
        user_interests: str | None = None
    ):
        """Отправляет резюме пользователю с маркировкой по интересам"""
        import telegramify_markdown
        from telegramify_markdown import customize
        from aiogram.enums import ParseMode

        customize.strict_markdown = False

        # Проверяем соответствие интересам
        is_interesting = False
        if user_interests:
            try:
                is_interesting = await self.summarizer.check_interests(summary, user_interests)
                # Небольшая задержка после проверки (rate limit)
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Interest check failed: {e}")

        # Формируем маркер для важных постов
        # 🔥 — яркий маркер, хорошо виден при скролле
        interest_marker = ""
        if is_interesting:
            interest_marker = "🔥🔥🔥 **ПО ТВОИМ ИНТЕРЕСАМ** 🔥🔥🔥\n\n"
            logger.info(f"[MARKER] Post matches interests for user {telegram_id}")

        # Формируем сообщение
        if type_label:
            message = f"{interest_marker}**{type_label.strip()}**\n\n{summary}\n\n[Открыть в @{channel} →](https://t.me/{channel}/{post_id})"
        else:
            message = f"{interest_marker}{summary}\n\n[Открыть в @{channel} →](https://t.me/{channel}/{post_id})"

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
            plain_marker = "🔥🔥🔥 ПО ТВОИМ ИНТЕРЕСАМ 🔥🔥🔥\n\n" if is_interesting else ""
            if type_label:
                plain_message = f"{plain_marker}{type_label.strip()}\n\n{summary}\n\nОткрыть в @{channel}: https://t.me/{channel}/{post_id}"
            else:
                plain_message = f"{plain_marker}{summary}\n\nОткрыть в @{channel}: https://t.me/{channel}/{post_id}"
            await self.bot.send_message(telegram_id, plain_message)
