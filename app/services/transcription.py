import logging
import os
import tempfile
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Сервис для транскрипции аудио/видео через Whisper"""

    SUPPORTED_FORMATS = ['.mp3', '.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm', '.ogg', '.oga']

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")

        self.client = OpenAI(api_key=api_key)

    async def transcribe(self, file_path: str | Path, language: str = "ru") -> str:
        """
        Транскрибирует аудио/видео файл.

        Args:
            file_path: Путь к файлу
            language: Язык (по умолчанию русский)

        Returns:
            Текст транскрипции
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Проверяем формат
        suffix = file_path.suffix.lower()
        if suffix not in self.SUPPORTED_FORMATS:
            logger.warning(f"Unsupported format {suffix}, trying anyway...")

        try:
            with open(file_path, "rb") as audio_file:
                logger.info(f"Transcribing file: {file_path.name}")

                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=language,
                    response_format="text"
                )

                logger.info(f"Transcription completed: {len(transcript)} chars")
                return transcript

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            raise

    async def transcribe_bytes(self, data: bytes, filename: str = "audio.ogg", language: str = "ru") -> str:
        """
        Транскрибирует аудио из байтов.

        Args:
            data: Аудио данные
            filename: Имя файла (для определения формата)
            language: Язык

        Returns:
            Текст транскрипции
        """
        # Создаём временный файл
        suffix = Path(filename).suffix or ".ogg"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            return await self.transcribe(tmp_path, language)
        finally:
            # Удаляем временный файл
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# Ленивая инициализация
_transcription_service = None


def get_transcription_service() -> TranscriptionService:
    global _transcription_service
    if _transcription_service is None:
        _transcription_service = TranscriptionService()
    return _transcription_service
