import google.generativeai as genai
import logging
import os
import asyncio
import re

logger = logging.getLogger(__name__)


class Summarizer:
    """Сервис для создания резюме через Gemini"""

    MAX_RETRIES = 3

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-3-flash-preview")

    async def summarize(self, text: str, channel_name: str | None = None) -> tuple[str, dict]:
        """
        Создаёт резюме текста с retry при rate limit.

        Returns:
            tuple: (summary_text, usage_stats)
        """
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

                # Проверяем на rate limit (429)
                if "429" in error_str or "quota" in error_str.lower():
                    # Пытаемся извлечь время ожидания
                    wait_time = self._extract_retry_delay(error_str)
                    if wait_time is None:
                        wait_time = (attempt + 1) * 60  # 60, 120, 180 сек

                    logger.warning(
                        f"Rate limit hit, waiting {wait_time}s before retry "
                        f"(attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait_time)
                    continue

                # Другие ошибки — не ретраим
                logger.error(f"Summarization error: {e}")
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
