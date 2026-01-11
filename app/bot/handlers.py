import logging
import tempfile
import os
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from sqlalchemy import select, func

from app.db.database import get_async_session
from app.db.models import User, Channel, Subscription
from app.services.parser import ChannelParser
from app.services.summarizer import Summarizer
from app.services.transcription import TranscriptionService
from app.services.userbot import get_userbot_service, AuthState

import telegramify_markdown
from telegramify_markdown import customize

customize.strict_markdown = False

logger = logging.getLogger(__name__)
router = Router()

# Ленивая инициализация сервисов
_parser = None
_summarizer = None
_transcriber = None


def get_parser():
    global _parser
    if _parser is None:
        _parser = ChannelParser()
    return _parser


def get_summarizer():
    global _summarizer
    if _summarizer is None:
        _summarizer = Summarizer()
    return _summarizer


def get_transcriber():
    global _transcriber
    if _transcriber is None:
        _transcriber = TranscriptionService()
    return _transcriber


def setup_handlers(dp: Dispatcher):
    """Регистрирует все хендлеры"""
    dp.include_router(router)


async def get_or_create_user(telegram_id: int, username: str | None, first_name: str | None) -> User:
    """Получает или создаёт пользователя"""
    async with get_async_session()() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info(f"Created new user: {telegram_id}")

        return user


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик /start"""
    await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    text = """**Привет! Я бот для создания резюме постов из Telegram-каналов.**

**Как пользоваться:**
1. Перешли мне любое сообщение из публичного канала
2. Я добавлю этот канал в твой дайджест
3. Когда появятся новые посты — пришлю тебе резюме

**Команды:**
/channels — список твоих каналов
/remove @channel — отписаться от канала
/help — справка"""

    formatted = telegramify_markdown.markdownify(text)
    await message.answer(formatted, parse_mode=ParseMode.MARKDOWN_V2)


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик /help"""
    text = """**Справка по боту**

**Добавление канала:**
Перешли любое сообщение из публичного канала, и он автоматически добавится в твой дайджест.

**Команды:**
/channels — показать все твои каналы
/remove @channelname — отписаться от канала
/stats — статистика

**Как это работает:**
Бот проверяет каналы каждые 5 минут. Когда появляется новый пост, создаётся краткое резюме с помощью AI и отправляется тебе."""

    formatted = telegramify_markdown.markdownify(text)
    await message.answer(formatted, parse_mode=ParseMode.MARKDOWN_V2)


@router.message(Command("channels"))
async def cmd_channels(message: types.Message):
    """Показывает список каналов пользователя"""
    async with get_async_session()() as session:
        result = await session.execute(
            select(Subscription)
            .join(User)
            .join(Channel)
            .where(User.telegram_id == message.from_user.id)
            .options()
        )
        subscriptions = result.scalars().all()

        if not subscriptions:
            await message.answer("У тебя пока нет подписок на каналы.\n\nПерешли сообщение из любого канала, чтобы добавить его.")
            return

        # Получаем каналы
        channel_ids = [s.channel_id for s in subscriptions]
        channels_result = await session.execute(
            select(Channel).where(Channel.id.in_(channel_ids))
        )
        channels = channels_result.scalars().all()

        text = "**Твои каналы:**\n\n"
        for ch in channels:
            status = "✅" if ch.is_active else "❌"
            text += f"{status} @{ch.username}"
            if ch.title:
                text += f" — {ch.title}"
            text += "\n"

        text += f"\n_Всего: {len(channels)} каналов_"

        formatted = telegramify_markdown.markdownify(text)
        await message.answer(formatted, parse_mode=ParseMode.MARKDOWN_V2)


@router.message(Command("add"))
async def cmd_add(message: types.Message):
    """Добавление каналов по username (можно несколько через пробел)"""
    args = message.text.split()[1:]  # Убираем /add
    if not args:
        await message.answer("Использование: /add @channel1 @channel2 @channel3")
        return

    # Парсим каналы из аргументов
    channels_to_add = []
    for arg in args:
        # Убираем @ и лишние символы
        username = arg.replace("@", "").strip().lower()
        if username and username not in channels_to_add:
            channels_to_add.append(username)

    if not channels_to_add:
        await message.answer("Не найдено каналов для добавления")
        return

    await message.answer(f"Добавляю {len(channels_to_add)} каналов...")

    added = []
    already_exists = []
    failed = []

    async with get_async_session()() as session:
        # Получаем или создаём пользователя
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
            session.add(user)
            await session.flush()

        for channel_username in channels_to_add:
            try:
                # Проверяем доступность канала
                is_public = await get_parser().is_channel_public(channel_username)
                if not is_public:
                    failed.append(f"@{channel_username} (недоступен)")
                    continue

                # Получаем или создаём канал
                channel_result = await session.execute(
                    select(Channel).where(Channel.username == channel_username)
                )
                channel = channel_result.scalar_one_or_none()

                # Получаем ID последнего поста
                latest_post_id = 0
                try:
                    posts = await get_parser().get_posts(channel_username, 0)
                    if posts:
                        latest_post_id = max(p.post_id for p in posts)
                except Exception as e:
                    logger.warning(f"Could not get latest post for @{channel_username}: {e}")

                if not channel:
                    info = await get_parser().get_channel_info(channel_username)
                    channel = Channel(
                        username=channel_username,
                        title=info.title if info else channel_username,
                        last_post_id=latest_post_id,
                    )
                    session.add(channel)
                    await session.flush()
                    logger.info(f"Created channel @{channel_username} (last_post_id={latest_post_id})")
                else:
                    # Обновляем last_post_id для существующего канала
                    if latest_post_id > 0:
                        channel.last_post_id = latest_post_id
                        logger.info(f"Updated @{channel_username} last_post_id={latest_post_id}")

                # Проверяем подписку
                sub_result = await session.execute(
                    select(Subscription).where(
                        Subscription.user_id == user.id,
                        Subscription.channel_id == channel.id
                    )
                )
                if sub_result.scalar_one_or_none():
                    already_exists.append(f"@{channel_username}")
                    continue

                # Создаём подписку
                subscription = Subscription(user_id=user.id, channel_id=channel.id)
                session.add(subscription)
                added.append(f"@{channel_username}")

            except Exception as e:
                logger.error(f"Error adding channel @{channel_username}: {e}")
                failed.append(f"@{channel_username} (ошибка)")

        await session.commit()

    # Формируем ответ
    result_parts = []
    if added:
        result_parts.append(f"✅ Добавлено: {', '.join(added)}")
    if already_exists:
        result_parts.append(f"ℹ️ Уже есть: {', '.join(already_exists)}")
    if failed:
        result_parts.append(f"❌ Ошибка: {', '.join(failed)}")

    await message.answer("\n".join(result_parts) or "Ничего не добавлено")


@router.message(Command("remove"))
async def cmd_remove(message: types.Message):
    """Отписка от канала или от всех каналов"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование:\n/remove @channelname — отписаться от канала\n/remove all — отписаться от всех")
        return

    arg = args[1].strip().lower()

    async with get_async_session()() as session:
        # Находим пользователя
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            await message.answer("Ошибка: пользователь не найден")
            return

        # Удаление всех подписок
        if arg == "all":
            sub_result = await session.execute(
                select(Subscription).where(Subscription.user_id == user.id)
            )
            subscriptions = sub_result.scalars().all()

            if not subscriptions:
                await message.answer("У тебя нет подписок")
                return

            count = len(subscriptions)
            for sub in subscriptions:
                await session.delete(sub)
            await session.commit()

            await message.answer(f"✅ Удалено {count} подписок")
            return

        # Удаление одной подписки
        channel_username = arg.replace("@", "")

        # Находим канал
        channel_result = await session.execute(
            select(Channel).where(Channel.username == channel_username)
        )
        channel = channel_result.scalar_one_or_none()
        if not channel:
            await message.answer(f"Канал @{channel_username} не найден")
            return

        # Удаляем подписку
        sub_result = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.channel_id == channel.id
            )
        )
        subscription = sub_result.scalar_one_or_none()

        if not subscription:
            await message.answer(f"Ты не подписан на @{channel_username}")
            return

        await session.delete(subscription)
        await session.commit()

        await message.answer(f"✅ Отписался от @{channel_username}")


@router.message(Command("refresh"))
async def cmd_refresh(message: types.Message):
    """Принудительная проверка каналов"""
    from app.services.scheduler import get_scheduler

    scheduler = get_scheduler()
    if not scheduler:
        await message.answer("❌ Scheduler не запущен")
        return

    await message.answer("🔄 Запускаю проверку каналов...")

    try:
        await scheduler._check_channels()
        await message.answer("✅ Проверка завершена")
    except Exception as e:
        logger.error(f"Refresh error: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Статистика пользователя"""
    async with get_async_session()() as session:
        # Количество подписок пользователя
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            await message.answer("Ошибка: пользователь не найден")
            return

        subs_count = await session.execute(
            select(func.count(Subscription.id)).where(Subscription.user_id == user.id)
        )
        subs = subs_count.scalar()

        # Общая статистика
        total_users = await session.execute(select(func.count(User.id)))
        total_channels = await session.execute(select(func.count(Channel.id)))

        text = f"""**Статистика**

Твоих подписок: {subs}
Всего пользователей: {total_users.scalar()}
Всего каналов: {total_channels.scalar()}"""

        formatted = telegramify_markdown.markdownify(text)
        await message.answer(formatted, parse_mode=ParseMode.MARKDOWN_V2)


@router.message()
async def handle_message(message: types.Message):
    """Обработчик всех остальных сообщений"""
    # Проверяем, это пересланное сообщение из канала?
    if message.forward_from_chat and message.forward_from_chat.type == "channel":
        await handle_forwarded_channel_message(message)
        return

    # Проверяем голосовые сообщения
    if message.voice:
        await handle_voice_message(message)
        return

    # Проверяем видео-кружки
    if message.video_note:
        await handle_video_note(message)
        return

    # Проверяем аудио
    if message.audio:
        await handle_audio_message(message)
        return

    # Обычное текстовое сообщение — делаем резюме
    text = message.text or message.caption

    if not text:
        await message.answer(
            "Отправь мне:\n"
            "• Текст — сделаю резюме\n"
            "• Голосовое — транскрибирую и сделаю резюме\n"
            "• Кружок — транскрибирую и сделаю резюме\n"
            "• Пересланное сообщение из канала — добавлю в дайджест"
        )
        return

    if len(text) < 20:
        await message.answer("Текст слишком короткий для резюме.")
        return

    # Делаем резюме
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        summary, stats = await get_summarizer().summarize(text)

        formatted = telegramify_markdown.markdownify(summary)
        await message.answer(formatted, parse_mode=ParseMode.MARKDOWN_V2)

        logger.info(f"[TOKENS] User: {message.from_user.id} | Stats: {stats}")

    except Exception as e:
        logger.error(f"Summarization error: {e}")
        await message.answer(f"Ошибка при создании резюме: {str(e)}")


async def handle_forwarded_channel_message(message: types.Message):
    """Обрабатывает пересланное сообщение из канала"""
    channel_username = message.forward_from_chat.username

    if not channel_username:
        await message.answer("Этот канал приватный, я не могу его отслеживать.")
        return

    # Проверяем, публичный ли канал
    is_public = await get_parser().is_channel_public(channel_username)
    if not is_public:
        await message.answer(f"Канал @{channel_username} недоступен (приватный или не существует).")
        return

    async with get_async_session()() as session:
        # Получаем или создаём пользователя
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
            session.add(user)
            await session.flush()

        # Получаем или создаём канал
        channel_result = await session.execute(
            select(Channel).where(Channel.username == channel_username)
        )
        channel = channel_result.scalar_one_or_none()

        if not channel:
            # Получаем информацию о канале
            info = await get_parser().get_channel_info(channel_username)

            # Используем ID пересланного поста как стартовую точку
            # Чтобы не обрабатывать старые посты
            forwarded_post_id = message.forward_from_message_id or 0

            channel = Channel(
                username=channel_username,
                title=info.title if info else message.forward_from_chat.title,
                last_post_id=forwarded_post_id,  # Начинаем с текущего поста
            )
            session.add(channel)
            await session.flush()
            logger.info(f"Created new channel: @{channel_username} (starting from post {forwarded_post_id})")

        # Проверяем, есть ли уже подписка
        sub_result = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.channel_id == channel.id
            )
        )
        existing_sub = sub_result.scalar_one_or_none()

        if existing_sub:
            await message.answer(f"Ты уже подписан на @{channel_username}")
            return

        # Создаём подписку
        subscription = Subscription(user_id=user.id, channel_id=channel.id)
        session.add(subscription)
        await session.commit()

        title = channel.title or channel_username

        # Проверяем, авторизован ли userbot (для полного парсинга медиа)
        userbot_available = False
        try:
            userbot = get_userbot_service()
            status = await userbot.get_status()
            userbot_available = status.get("state") == AuthState.AUTHORIZED
        except Exception:
            pass

        # Формируем ответ
        response = f"✅ Канал **@{channel_username}** добавлен в твой дайджест!\n\n"
        if userbot_available:
            response += "Буду присылать резюме новых постов, включая голосовые и кружки."
        else:
            response += "Буду присылать резюме текстовых постов.\n\n_Голосовые из каналов пока недоступны._"

        await message.answer(response, parse_mode=ParseMode.MARKDOWN)

        logger.info(f"User {message.from_user.id} subscribed to @{channel_username}")


async def handle_voice_message(message: types.Message):
    """Обрабатывает голосовое сообщение"""
    logger.info(f"[VOICE] Processing voice from user {message.from_user.id}")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Скачиваем файл
        logger.info(f"[VOICE] Downloading file {message.voice.file_id}")
        file = await message.bot.get_file(message.voice.file_id)
        file_data = await message.bot.download_file(file.file_path)
        logger.info(f"[VOICE] Downloaded, size: {len(file_data.getvalue())} bytes")

        # Транскрибируем
        await message.answer("🎤 Транскрибирую голосовое...")
        logger.info("[VOICE] Starting transcription...")
        transcript = await get_transcriber().transcribe_bytes(
            file_data.read(),
            filename="voice.ogg"
        )
        logger.info(f"[VOICE] Transcription done: {len(transcript) if transcript else 0} chars")

        if not transcript or len(transcript.strip()) < 10:
            await message.answer("Не удалось распознать речь в голосовом сообщении.")
            return

        # Делаем резюме если текст достаточно длинный
        if len(transcript) > 100:
            await message.answer("📝 Создаю резюме...")
            summary, stats = await get_summarizer().summarize(transcript)

            response = f"**🎤 Транскрипция:**\n{transcript}\n\n**📝 Резюме:**\n{summary}"
        else:
            response = f"**🎤 Транскрипция:**\n{transcript}"

        formatted = telegramify_markdown.markdownify(response)
        await message.answer(formatted, parse_mode=ParseMode.MARKDOWN_V2)

        logger.info(f"Voice transcribed for user {message.from_user.id}: {len(transcript)} chars")

    except Exception as e:
        logger.error(f"Voice transcription error: {e}")
        await message.answer(f"Ошибка при обработке голосового: {str(e)}")


async def handle_video_note(message: types.Message):
    """Обрабатывает видео-кружок"""
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Скачиваем файл
        file = await message.bot.get_file(message.video_note.file_id)
        file_data = await message.bot.download_file(file.file_path)

        # Транскрибируем
        await message.answer("🔵 Транскрибирую кружок...")
        transcript = await get_transcriber().transcribe_bytes(
            file_data.read(),
            filename="video_note.mp4"
        )

        if not transcript or len(transcript.strip()) < 10:
            await message.answer("Не удалось распознать речь в кружке.")
            return

        # Делаем резюме если текст достаточно длинный
        if len(transcript) > 100:
            await message.answer("📝 Создаю резюме...")
            summary, stats = await get_summarizer().summarize(transcript)

            response = f"**🔵 Транскрипция кружка:**\n{transcript}\n\n**📝 Резюме:**\n{summary}"
        else:
            response = f"**🔵 Транскрипция кружка:**\n{transcript}"

        formatted = telegramify_markdown.markdownify(response)
        await message.answer(formatted, parse_mode=ParseMode.MARKDOWN_V2)

        logger.info(f"Video note transcribed for user {message.from_user.id}: {len(transcript)} chars")

    except Exception as e:
        logger.error(f"Video note transcription error: {e}")
        await message.answer(f"Ошибка при обработке кружка: {str(e)}")


async def handle_audio_message(message: types.Message):
    """Обрабатывает аудио файл"""
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Скачиваем файл
        file = await message.bot.get_file(message.audio.file_id)
        file_data = await message.bot.download_file(file.file_path)

        # Определяем расширение
        filename = message.audio.file_name or "audio.mp3"

        # Транскрибируем
        await message.answer("🎵 Транскрибирую аудио...")
        transcript = await get_transcriber().transcribe_bytes(
            file_data.read(),
            filename=filename
        )

        if not transcript or len(transcript.strip()) < 10:
            await message.answer("Не удалось распознать речь в аудио.")
            return

        # Делаем резюме если текст достаточно длинный
        if len(transcript) > 100:
            await message.answer("📝 Создаю резюме...")
            summary, stats = await get_summarizer().summarize(transcript)

            response = f"**🎵 Транскрипция аудио:**\n{transcript}\n\n**📝 Резюме:**\n{summary}"
        else:
            response = f"**🎵 Транскрипция аудио:**\n{transcript}"

        formatted = telegramify_markdown.markdownify(response)
        await message.answer(formatted, parse_mode=ParseMode.MARKDOWN_V2)

        logger.info(f"Audio transcribed for user {message.from_user.id}: {len(transcript)} chars")

    except Exception as e:
        logger.error(f"Audio transcription error: {e}")
        await message.answer(f"Ошибка при обработке аудио: {str(e)}")
