import google.generativeai as genai
import logging
import os
import asyncio
import re
import base64
from typing import Optional

from app.services.settings import get_current_model, get_setting

logger = logging.getLogger(__name__)


class Summarizer:
    """Сервис для создания резюме через Gemini"""

    MAX_RETRIES = 3

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")

        genai.configure(api_key=api_key)
        self._current_model_name: str | None = None
        self.model = None
        self._ensure_model()

    def _ensure_model(self):
        """Проверяет и обновляет модель если она изменилась в настройках"""
        model_name = get_current_model()

        if model_name != self._current_model_name:
            logger.info(f"Switching to model: {model_name}")
            self.model = genai.GenerativeModel(model_name)
            self._current_model_name = model_name

    def get_model_name(self) -> str:
        """Возвращает имя текущей модели"""
        return self._current_model_name or "unknown"

    async def summarize(self, text: str, channel_name: str | None = None) -> tuple[str, dict]:
        """
        Создаёт резюме текста с retry при rate limit.

        Returns:
            tuple: (summary_text, usage_stats)
        """
        self._ensure_model()  # Проверяем актуальность модели
        prompt = self._build_prompt(text, channel_name)

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.model.generate_content(prompt)

                # Статистика токенов
                usage = response.usage_metadata
                stats = {
                    "input_tokens": usage.prompt_token_count,
                    "output_tokens": usage.candidates_token_count,
                    "total_tokens": usage.total_token_count,
                }

                logger.info(
                    f"[TOKENS] Input: {stats['input_tokens']} | "
                    f"Output: {stats['output_tokens']} | Total: {stats['total_tokens']}"
                )

                return response.text, stats

            except Exception as e:
                error_str = str(e)

                # ВСЕГДА логируем полную ошибку для диагностики
                logger.error(f"Gemini API error (attempt {attempt + 1}): {error_str}")

                # Проверяем на rate limit (429)
                if "429" in error_str or "quota" in error_str.lower() or "resource" in error_str.lower():
                    # Пытаемся извлечь время ожидания
                    wait_time = self._extract_retry_delay(error_str)
                    if wait_time is None:
                        wait_time = (attempt + 1) * 60  # 60, 120, 180 сек

                    logger.warning(
                        f"Rate limit detected, waiting {wait_time}s before retry "
                        f"(attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait_time)
                    continue

                # Другие ошибки — не ретраим
                raise

        # Все попытки исчерпаны
        raise Exception(f"Failed after {self.MAX_RETRIES} retries due to rate limits")

    def _extract_retry_delay(self, error_str: str) -> int | None:
        """Извлекает время ожидания из ошибки"""
        # Ищем "retry in X.XXs" или "seconds: X"
        match = re.search(r'retry in (\d+)', error_str, re.IGNORECASE)
        if match:
            return int(match.group(1)) + 5  # +5 секунд запас

        match = re.search(r'seconds:\s*(\d+)', error_str)
        if match:
            return int(match.group(1)) + 5

        return None

    def _build_prompt(self, text: str, channel_name: str | None = None) -> str:
        """Строит промпт для резюме"""
        channel_context = f" из канала @{channel_name}" if channel_name else ""

        return f"""Сделай краткое и информативное резюме следующего поста{channel_context}.

Требования:
- Резюме на русском языке
- Выдели 2-3 ключевые мысли
- Используй маркированный список для основных пунктов
- Будь лаконичен (максимум 3-4 предложения)
- Если есть цифры/даты/имена — сохрани их

Текст поста:
{text}"""

    async def summarize_batch(self, posts: list[dict]) -> str:
        """
        Создаёт общее резюме для нескольких постов (дайджест).
        """
        if not posts:
            return "Нет новых постов для резюме."

        combined_text = "\n\n---\n\n".join([
            f"Пост {i+1} (@{p.get('channel', 'unknown')}):\n{p.get('content', '')}"
            for i, p in enumerate(posts)
        ])

        prompt = f"""Создай краткий дайджест из следующих постов.

Требования:
- Резюме на русском языке
- Для каждого поста — 1-2 предложения с сутью
- Укажи канал-источник
- Общий объём — не более 10 предложений

Посты:
{combined_text}"""

        self._ensure_model()

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.model.generate_content(prompt)

                usage = response.usage_metadata
                logger.info(
                    f"[BATCH TOKENS] Input: {usage.prompt_token_count} | "
                    f"Output: {usage.candidates_token_count}"
                )

                return response.text

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "quota" in error_str.lower():
                    wait_time = self._extract_retry_delay(error_str) or (attempt + 1) * 60
                    logger.warning(f"Rate limit hit, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue

                logger.error(f"Batch summarization error: {e}")
                raise

        raise Exception(f"Batch failed after {self.MAX_RETRIES} retries")

    async def describe_image(self, image_data: bytes, context: str = "") -> str:
        """
        Описывает изображение с помощью Gemma Vision.

        Args:
            image_data: Байты изображения (JPEG/PNG)
            context: Дополнительный контекст (например, текст поста)

        Returns:
            Описание изображения
        """
        # Определяем MIME-тип
        if image_data[:8] == b'\x89PNG\r\n\x1a\n':
            mime_type = "image/png"
        elif image_data[:2] == b'\xff\xd8':
            mime_type = "image/jpeg"
        else:
            mime_type = "image/jpeg"  # По умолчанию

        # Кодируем в base64
        image_b64 = base64.b64encode(image_data).decode("utf-8")

        context_part = f"\n\nКонтекст поста: {context}" if context else ""

        prompt = f"""Кратко опиши что изображено на этой картинке.{context_part}

Требования:
- На русском языке
- 1-2 предложения
- Только важные детали (люди, текст, объекты)
- Если есть текст на изображении — процитируй его"""

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.model.generate_content([
                    prompt,
                    {
                        "mime_type": mime_type,
                        "data": image_b64
                    }
                ])

                usage = response.usage_metadata
                logger.info(
                    f"[IMAGE TOKENS] Input: {usage.prompt_token_count} | "
                    f"Output: {usage.candidates_token_count}"
                )

                # Проверяем что ответ не пустой
                try:
                    result_text = response.text if response.text else ""
                except ValueError as ve:
                    # response.text может выбросить исключение если заблокирован
                    logger.warning(f"Cannot access response.text: {ve}")
                    result_text = ""

                if not result_text.strip():
                    logger.warning(f"Empty response from model for image, attempt {attempt + 1}")
                    # Логируем причину
                    if hasattr(response, 'prompt_feedback'):
                        logger.warning(f"Prompt feedback: {response.prompt_feedback}")
                    if attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(2)
                        continue
                    return "Изображение (описание недоступно)"

                return result_text

            except Exception as e:
                error_str = str(e)
                logger.error(f"Image description error (attempt {attempt + 1}): {error_str}")

                if "429" in error_str or "quota" in error_str.lower() or "resource" in error_str.lower():
                    wait_time = self._extract_retry_delay(error_str) or (attempt + 1) * 60
                    logger.warning(f"Rate limit hit, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue

                raise

        raise Exception(f"Image description failed after {self.MAX_RETRIES} retries")

    async def describe_images(self, images: list[bytes], context: str = "") -> str:
        """
        Описывает несколько изображений (альбом).

        Args:
            images: Список байтов изображений
            context: Дополнительный контекст

        Returns:
            Общее описание альбома
        """
        if not images:
            return ""

        if len(images) == 1:
            return await self.describe_image(images[0], context)

        # Для нескольких изображений - описываем все сразу
        image_parts = []
        for img_data in images[:10]:  # Максимум 10 изображений
            if img_data[:8] == b'\x89PNG\r\n\x1a\n':
                mime_type = "image/png"
            elif img_data[:2] == b'\xff\xd8':
                mime_type = "image/jpeg"
            else:
                mime_type = "image/jpeg"

            image_parts.append({
                "mime_type": mime_type,
                "data": base64.b64encode(img_data).decode("utf-8")
            })

        context_part = f"\n\nКонтекст поста: {context}" if context else ""

        prompt = f"""Опиши этот альбом из {len(images)} изображений.{context_part}

Требования:
- На русском языке
- 1-2 предложения на каждое изображение
- Общая тема альбома если есть
- Важные детали и текст на изображениях"""

        for attempt in range(self.MAX_RETRIES):
            try:
                # Собираем запрос: промпт + все изображения
                content = [prompt] + image_parts
                response = self.model.generate_content(content)

                usage = response.usage_metadata
                logger.info(
                    f"[ALBUM TOKENS] Input: {usage.prompt_token_count} | "
                    f"Output: {usage.candidates_token_count}"
                )

                return response.text

            except Exception as e:
                error_str = str(e)
                logger.error(f"Album description error (attempt {attempt + 1}): {error_str}")

                if "429" in error_str or "quota" in error_str.lower() or "resource" in error_str.lower():
                    wait_time = self._extract_retry_delay(error_str) or (attempt + 1) * 60
                    logger.warning(f"Rate limit hit, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue

                raise

        raise Exception(f"Album description failed after {self.MAX_RETRIES} retries")

    async def summarize_multimodal(
        self,
        text: str = "",
        images: list[bytes] = None,
        audio_transcript: str = "",
        channel_name: str = "",
        content_types: list[str] = None
    ) -> tuple[str, dict]:
        """
        Создаёт резюме мультимодального поста (текст + изображения + аудио).

        Args:
            text: Текстовое содержимое поста
            images: Список изображений (bytes)
            audio_transcript: Транскрипция аудио/видео
            channel_name: Название канала
            content_types: Типы контента для маркировки

        Returns:
            tuple: (summary_text, usage_stats)
        """
        images = images or []
        content_types = content_types or []

        # Собираем все части контента
        parts = []

        if text:
            parts.append(f"Текст поста:\n{text}")

        if audio_transcript:
            parts.append(f"Транскрипция аудио/видео:\n{audio_transcript}")

        # Описываем изображения если есть
        if images:
            try:
                image_desc = await self.describe_images(images, context=text)
                parts.append(f"Изображения ({len(images)} шт):\n{image_desc}")
                await asyncio.sleep(5)  # Rate limit для Gemini
            except Exception as e:
                logger.error(f"Failed to describe images: {e}")
                parts.append(f"Изображения: {len(images)} шт (не удалось описать)")

        if not parts:
            return "Пустой пост", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        combined_content = "\n\n---\n\n".join(parts)

        # Формируем маркеры типов контента
        type_markers = []
        if "text" in content_types or text:
            type_markers.append("📝 текст")
        if "photo" in content_types or images:
            type_markers.append(f"📷 фото ({len(images)})")
        if "voice" in content_types:
            type_markers.append("🎤 голосовое")
        if "video_note" in content_types:
            type_markers.append("🔵 кружок")
        if "video" in content_types:
            type_markers.append("🎬 видео")
        if "audio" in content_types:
            type_markers.append("🎵 аудио")

        type_label = " | ".join(type_markers) if type_markers else ""

        channel_context = f" из канала @{channel_name}" if channel_name else ""

        prompt = f"""Сделай краткое резюме следующего поста{channel_context}.

Типы контента: {type_label}

{combined_content}

Требования:
- Резюме на русском языке
- 2-3 ключевые мысли
- Маркированный список для основных пунктов
- Максимум 4-5 предложений
- Сохрани важные цифры/даты/имена
- НЕ начинай с "В посте..." или "Пост содержит..."
"""

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.model.generate_content(prompt)

                usage = response.usage_metadata
                stats = {
                    "input_tokens": usage.prompt_token_count,
                    "output_tokens": usage.candidates_token_count,
                    "total_tokens": usage.total_token_count,
                }

                logger.info(
                    f"[MULTIMODAL TOKENS] Input: {stats['input_tokens']} | "
                    f"Output: {stats['output_tokens']}"
                )

                # Проверяем что ответ не пустой
                result_text = response.text if response.text else ""
                if not result_text.strip():
                    logger.warning(f"Empty response from model, attempt {attempt + 1}")
                    # Проверяем причину блокировки
                    if response.candidates:
                        for candidate in response.candidates:
                            if candidate.finish_reason:
                                logger.warning(f"Finish reason: {candidate.finish_reason}")
                            if hasattr(candidate, 'safety_ratings'):
                                logger.warning(f"Safety ratings: {candidate.safety_ratings}")
                    if attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(2)
                        continue
                    # Fallback - возвращаем краткое описание контента
                    fallback = "Контент обработан"
                    if type_label:
                        fallback = f"[{type_label}]\n\n{fallback}"
                    return fallback, stats

                # Добавляем маркер типов в начало если есть
                summary = result_text
                if type_label:
                    summary = f"[{type_label}]\n\n{summary}"

                return summary, stats

            except Exception as e:
                error_str = str(e)
                logger.error(f"Multimodal summarize error (attempt {attempt + 1}): {error_str}")

                if "429" in error_str or "quota" in error_str.lower() or "resource" in error_str.lower():
                    wait_time = self._extract_retry_delay(error_str) or (attempt + 1) * 60
                    logger.warning(f"Rate limit hit, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue

                raise

        raise Exception(f"Multimodal summarize failed after {self.MAX_RETRIES} retries")

    async def check_interests(self, summary: str, interests: str) -> bool:
        """
        Проверяет, соответствует ли резюме интересам пользователя.

        Args:
            summary: Резюме поста
            interests: Описание интересов пользователя

        Returns:
            True если пост соответствует интересам
        """
        if not interests or not summary:
            return False

        prompt = f"""Определи, соответствует ли пост интересам пользователя.

Интересы пользователя: {interests}

Содержание поста:
{summary}

Ответь ТОЛЬКО одним словом: ДА или НЕТ
- ДА — если пост явно связан с интересами пользователя
- НЕТ — если пост не связан или связь слабая"""

        try:
            response = self.model.generate_content(prompt)

            usage = response.usage_metadata
            logger.debug(
                f"[INTERESTS CHECK] Input: {usage.prompt_token_count} | "
                f"Output: {usage.candidates_token_count}"
            )

            result = response.text.strip().upper() if response.text else ""

            # Проверяем ответ
            matches = "ДА" in result or "YES" in result

            logger.info(f"[INTERESTS] Match: {matches} | Response: {result[:20]}")

            return matches

        except Exception as e:
            logger.error(f"Interest check error: {e}")
            return False  # При ошибке не помечаем как важное
