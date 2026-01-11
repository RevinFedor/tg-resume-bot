"""
Userbot сервис для парсинга медиа из Telegram каналов через MTProto.

Использует Pyrogram для авторизации реального Telegram аккаунта,
который может получать голосовые, кружки и видео из каналов.
"""
import asyncio
import logging
import os
import tempfile
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PasswordHashInvalid,
    FloodWait,
    BadRequest,
    ChannelPrivate,
)
from sqlalchemy import select

from app.db.database import get_async_session
from app.db.models import UserbotSession, Channel

logger = logging.getLogger(__name__)


class AuthState(str, Enum):
    """Состояния авторизации userbot"""
    NOT_STARTED = "not_started"
    WAITING_CODE = "waiting_code"
    WAITING_PASSWORD = "waiting_password"
    AUTHORIZED = "authorized"
    ERROR = "error"


class UserbotService:
    """
    Сервис для управления userbot через Pyrogram.

    Позволяет:
    - Авторизовать Telegram аккаунт (телефон → код → 2FA)
    - Подписываться на каналы
    - Скачивать медиа (голосовые, кружки, видео)
    """

    def __init__(self):
        self.api_id = os.getenv("TELEGRAM_API_ID")
        self.api_hash = os.getenv("TELEGRAM_API_HASH")
        self._client: Optional[Client] = None
        self._auth_state = AuthState.NOT_STARTED
        self._current_phone: Optional[str] = None
        self._phone_code_hash: Optional[str] = None

        if not self.api_id or not self.api_hash:
            logger.warning(
                "TELEGRAM_API_ID and TELEGRAM_API_HASH not set. "
                "Userbot features will be disabled. "
                "Get them from https://my.telegram.org/apps"
            )

    @property
    def is_configured(self) -> bool:
        """Проверяет, настроены ли API credentials"""
        return bool(self.api_id and self.api_hash)

    @property
    def auth_state(self) -> AuthState:
        return self._auth_state

    async def get_status(self) -> dict:
        """Возвращает текущий статус userbot"""
        if not self.is_configured:
            return {
                "configured": False,
                "state": AuthState.NOT_STARTED,
                "message": "TELEGRAM_API_ID и TELEGRAM_API_HASH не настроены",
            }

        # Проверяем сохранённую сессию в БД
        async with get_async_session()() as session:
            result = await session.execute(
                select(UserbotSession)
                .where(UserbotSession.is_active == True)
                .order_by(UserbotSession.created_at.desc())
                .limit(1)
            )
            db_session = result.scalar_one_or_none()

            if db_session and db_session.is_authorized:
                return {
                    "configured": True,
                    "state": AuthState.AUTHORIZED,
                    "phone": db_session.phone_number,
                    "message": "Userbot авторизован и готов к работе",
                }

        return {
            "configured": True,
            "state": self._auth_state,
            "phone": self._current_phone,
            "message": self._get_state_message(),
        }

    def _get_state_message(self) -> str:
        """Сообщение для текущего состояния"""
        messages = {
            AuthState.NOT_STARTED: "Авторизация не начата. Введите номер телефона.",
            AuthState.WAITING_CODE: "Ожидание кода подтверждения из Telegram.",
            AuthState.WAITING_PASSWORD: "Требуется пароль двухфакторной аутентификации.",
            AuthState.AUTHORIZED: "Userbot авторизован и готов к работе.",
            AuthState.ERROR: "Ошибка авторизации. Попробуйте снова.",
        }
        return messages.get(self._auth_state, "Неизвестное состояние")

    async def start_auth(self, phone_number: str) -> dict:
        """
        Начинает процесс авторизации.

        Args:
            phone_number: Номер телефона в международном формате (+7...)

        Returns:
            dict с результатом операции
        """
        if not self.is_configured:
            return {
                "success": False,
                "error": "API credentials не настроены",
            }

        # Нормализуем номер телефона
        phone_number = phone_number.strip().replace(" ", "").replace("-", "")
        if not phone_number.startswith("+"):
            phone_number = "+" + phone_number

        self._current_phone = phone_number

        try:
            # Создаём клиент с in-memory сессией
            self._client = Client(
                name="userbot_session",
                api_id=int(self.api_id),
                api_hash=self.api_hash,
                in_memory=True,
            )

            await self._client.connect()

            # Отправляем код
            sent_code = await self._client.send_code(phone_number)
            self._phone_code_hash = sent_code.phone_code_hash

            # Сохраняем в БД
            async with get_async_session()() as session:
                # Удаляем старые незавершённые сессии для этого номера
                old_result = await session.execute(
                    select(UserbotSession).where(
                        UserbotSession.phone_number == phone_number,
                        UserbotSession.is_authorized == False
                    )
                )
                for old_session in old_result.scalars().all():
                    await session.delete(old_session)

                # Создаём новую запись
                db_session = UserbotSession(
                    phone_number=phone_number,
                    phone_code_hash=self._phone_code_hash,
                    is_authorized=False,
                )
                session.add(db_session)
                await session.commit()

            self._auth_state = AuthState.WAITING_CODE

            logger.info(f"Auth code sent to {phone_number}")

            return {
                "success": True,
                "state": AuthState.WAITING_CODE,
                "message": f"Код отправлен на {phone_number}",
            }

        except FloodWait as e:
            logger.error(f"Flood wait: {e.value} seconds")
            return {
                "success": False,
                "error": f"Слишком много попыток. Подождите {e.value} секунд.",
            }
        except Exception as e:
            logger.error(f"Start auth error: {e}")
            self._auth_state = AuthState.ERROR
            return {
                "success": False,
                "error": str(e),
            }

    async def confirm_code(self, code: str) -> dict:
        """
        Подтверждает код из SMS/Telegram.

        Args:
            code: 5-значный код

        Returns:
            dict с результатом операции
        """
        if self._auth_state != AuthState.WAITING_CODE:
            return {
                "success": False,
                "error": "Сначала начните авторизацию с номера телефона",
            }

        if not self._client or not self._phone_code_hash:
            return {
                "success": False,
                "error": "Сессия авторизации не найдена. Начните заново.",
            }

        code = code.strip().replace(" ", "").replace("-", "")

        try:
            # Пробуем войти с кодом
            await self._client.sign_in(
                phone_number=self._current_phone,
                phone_code_hash=self._phone_code_hash,
                phone_code=code,
            )

            # Успешная авторизация!
            await self._save_session()

            return {
                "success": True,
                "state": AuthState.AUTHORIZED,
                "message": "Авторизация успешна!",
            }

        except SessionPasswordNeeded:
            # Нужен 2FA пароль
            self._auth_state = AuthState.WAITING_PASSWORD
            logger.info("2FA password required")

            return {
                "success": True,
                "state": AuthState.WAITING_PASSWORD,
                "message": "Требуется пароль двухфакторной аутентификации",
            }

        except PhoneCodeInvalid:
            return {
                "success": False,
                "error": "Неверный код. Проверьте и попробуйте снова.",
            }

        except PhoneCodeExpired:
            self._auth_state = AuthState.NOT_STARTED
            return {
                "success": False,
                "error": "Код истёк. Начните авторизацию заново.",
            }

        except Exception as e:
            logger.error(f"Confirm code error: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def confirm_password(self, password: str) -> dict:
        """
        Подтверждает 2FA пароль.

        Args:
            password: Пароль двухфакторной аутентификации

        Returns:
            dict с результатом операции
        """
        if self._auth_state != AuthState.WAITING_PASSWORD:
            return {
                "success": False,
                "error": "2FA пароль не требуется на данном этапе",
            }

        if not self._client:
            return {
                "success": False,
                "error": "Сессия авторизации не найдена. Начните заново.",
            }

        try:
            await self._client.check_password(password)

            # Успешная авторизация!
            await self._save_session()

            return {
                "success": True,
                "state": AuthState.AUTHORIZED,
                "message": "Авторизация успешна!",
            }

        except PasswordHashInvalid:
            return {
                "success": False,
                "error": "Неверный пароль. Проверьте и попробуйте снова.",
            }

        except Exception as e:
            logger.error(f"Confirm password error: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def _save_session(self):
        """Сохраняет сессию в БД после успешной авторизации"""
        if not self._client:
            return

        session_string = await self._client.export_session_string()

        async with get_async_session()() as session:
            # Деактивируем все старые сессии
            result = await session.execute(
                select(UserbotSession).where(UserbotSession.is_active == True)
            )
            for old_session in result.scalars().all():
                old_session.is_active = False

            # Обновляем текущую сессию
            result = await session.execute(
                select(UserbotSession).where(
                    UserbotSession.phone_number == self._current_phone
                ).order_by(UserbotSession.created_at.desc()).limit(1)
            )
            db_session = result.scalar_one_or_none()

            if db_session:
                db_session.session_string = session_string
                db_session.is_authorized = True
                db_session.is_active = True
                db_session.last_used_at = datetime.utcnow()
            else:
                db_session = UserbotSession(
                    phone_number=self._current_phone,
                    session_string=session_string,
                    is_authorized=True,
                    is_active=True,
                )
                session.add(db_session)

            await session.commit()

        self._auth_state = AuthState.AUTHORIZED
        logger.info(f"Session saved for {self._current_phone}")

    async def get_client(self) -> Optional[Client]:
        """
        Возвращает авторизованный клиент Pyrogram.

        Загружает сессию из БД если клиент не инициализирован.
        """
        if not self.is_configured:
            return None

        # Если клиент уже есть и подключён
        if self._client and self._client.is_connected:
            return self._client

        # Пробуем загрузить сессию из БД
        async with get_async_session()() as session:
            result = await session.execute(
                select(UserbotSession).where(
                    UserbotSession.is_active == True,
                    UserbotSession.is_authorized == True
                ).order_by(UserbotSession.created_at.desc()).limit(1)
            )
            db_session = result.scalar_one_or_none()

            if not db_session or not db_session.session_string:
                logger.debug("No authorized userbot session found")
                return None

            try:
                self._client = Client(
                    name="userbot_session",
                    api_id=int(self.api_id),
                    api_hash=self.api_hash,
                    session_string=db_session.session_string,
                )
                await self._client.start()

                self._current_phone = db_session.phone_number
                self._auth_state = AuthState.AUTHORIZED

                # Обновляем last_used_at
                db_session.last_used_at = datetime.utcnow()
                await session.commit()

                logger.info(f"Userbot client restored from session: {db_session.phone_number}")
                return self._client

            except Exception as e:
                logger.error(f"Failed to restore userbot session: {e}")
                # Помечаем сессию как невалидную
                db_session.is_authorized = False
                await session.commit()
                return None

    async def join_channel(self, username: str) -> dict:
        """
        Подписывается на канал.

        Args:
            username: Username канала (без @)

        Returns:
            dict с результатом
        """
        client = await self.get_client()
        if not client:
            return {
                "success": False,
                "error": "Userbot не авторизован",
            }

        username = username.replace("@", "").strip()

        try:
            await client.join_chat(username)
            logger.info(f"Joined channel @{username}")

            return {
                "success": True,
                "message": f"Подписался на @{username}",
            }

        except FloodWait as e:
            return {
                "success": False,
                "error": f"Подождите {e.value} секунд перед следующей подпиской",
            }
        except BadRequest as e:
            return {
                "success": False,
                "error": f"Не удалось подписаться: {e}",
            }
        except Exception as e:
            logger.error(f"Join channel error: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def download_media(self, chat_username: str, message_id: int) -> Optional[bytes]:
        """
        Скачивает медиа из сообщения канала.

        Args:
            chat_username: Username канала
            message_id: ID сообщения

        Returns:
            bytes с данными файла или None
        """
        client = await self.get_client()
        if not client:
            logger.warning("Cannot download media: userbot not authorized")
            return None

        try:
            # Получаем сообщение
            messages = await client.get_messages(chat_username, message_ids=message_id)
            if not messages:
                return None

            message = messages if not isinstance(messages, list) else messages[0]

            # Скачиваем медиа во временный файл
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name

            downloaded_path = await client.download_media(message, file_name=tmp_path)

            if downloaded_path:
                with open(downloaded_path, "rb") as f:
                    data = f.read()

                # Удаляем временный файл
                try:
                    os.unlink(downloaded_path)
                except Exception:
                    pass

                logger.info(f"Downloaded media from @{chat_username}/{message_id}: {len(data)} bytes")
                return data

            return None

        except FloodWait as e:
            logger.warning(f"FloodWait downloading from @{chat_username}: wait {e.value}s")
            return None
        except Exception as e:
            logger.error(f"Download media error: {e}")
            return None

    async def get_channel_messages(
        self,
        username: str,
        after_id: int = 0,
        limit: int = 10
    ) -> list[dict]:
        """
        Получает сообщения из канала.

        Args:
            username: Username канала
            after_id: Получать сообщения после этого ID
            limit: Максимальное количество сообщений

        Returns:
            Список сообщений с метаданными
        """
        client = await self.get_client()
        if not client:
            return []

        username = username.replace("@", "").strip()

        try:
            messages = []
            async for message in client.get_chat_history(username, limit=limit):
                if message.id <= after_id:
                    break

                msg_data = {
                    "id": message.id,
                    "date": message.date,
                    "text": message.text or message.caption or "",
                    "has_voice": bool(message.voice),
                    "has_video_note": bool(message.video_note),
                    "has_audio": bool(message.audio),
                    "has_video": bool(message.video),
                    "has_photo": bool(message.photo),
                    # Для альбомов (несколько фото/видео в одном посте)
                    "media_group_id": message.media_group_id,
                }

                # Собираем все типы медиа в посте
                media_types = []

                if message.voice:
                    media_types.append("voice")
                    msg_data["voice_duration"] = message.voice.duration
                if message.video_note:
                    media_types.append("video_note")
                    msg_data["video_note_duration"] = message.video_note.duration
                if message.audio:
                    media_types.append("audio")
                    msg_data["audio_duration"] = message.audio.duration
                if message.video:
                    media_types.append("video")
                    msg_data["video_duration"] = message.video.duration if message.video.duration else None
                if message.photo:
                    media_types.append("photo")
                    # Берём самое большое разрешение фото
                    msg_data["photo_file_id"] = message.photo.file_id

                # Для обратной совместимости - основной тип медиа
                if media_types:
                    msg_data["media_type"] = media_types[0]
                    msg_data["all_media_types"] = media_types
                else:
                    msg_data["media_type"] = "text"
                    msg_data["all_media_types"] = []

                messages.append(msg_data)

            logger.info(f"Got {len(messages)} messages from @{username}")
            return messages

        except FloodWait as e:
            # Telegram просит подождать - логируем и возвращаем пустой список
            logger.warning(f"FloodWait for @{username}: need to wait {e.value} seconds")
            return []
        except ChannelPrivate:
            logger.warning(f"Channel @{username} is private or inaccessible")
            return []
        except Exception as e:
            logger.error(f"Get channel messages error: {e}")
            return []

    async def download_photo(self, chat_username: str, message_id: int) -> Optional[bytes]:
        """
        Скачивает фото из сообщения канала.

        Args:
            chat_username: Username канала
            message_id: ID сообщения

        Returns:
            bytes с данными фото или None
        """
        return await self.download_media(chat_username, message_id)

    async def logout(self) -> dict:
        """Выходит из аккаунта и удаляет сессию"""
        try:
            if self._client and self._client.is_connected:
                await self._client.stop()

            # Деактивируем сессию в БД
            async with get_async_session()() as session:
                result = await session.execute(
                    select(UserbotSession).where(UserbotSession.is_active == True)
                )
                for db_session in result.scalars().all():
                    db_session.is_active = False
                    db_session.is_authorized = False
                await session.commit()

            self._client = None
            self._auth_state = AuthState.NOT_STARTED
            self._current_phone = None
            self._phone_code_hash = None

            logger.info("Userbot logged out")

            return {
                "success": True,
                "message": "Выход выполнен",
            }

        except Exception as e:
            logger.error(f"Logout error: {e}")
            return {
                "success": False,
                "error": str(e),
            }


# Глобальный экземпляр сервиса
_userbot_service: Optional[UserbotService] = None


def get_userbot_service() -> UserbotService:
    """Возвращает экземпляр UserbotService (singleton)"""
    global _userbot_service
    if _userbot_service is None:
        _userbot_service = UserbotService()
    return _userbot_service
