"""
Сервис для управления настройками приложения.

Настройки хранятся в БД и кешируются в памяти для быстрого доступа.
При изменении через API обновляется и БД, и кеш.
"""
import logging
from datetime import datetime
from typing import Any
from sqlalchemy import select

from app.db.database import get_async_session
from app.db.models import AppSettings

logger = logging.getLogger(__name__)


# Дефолтные настройки
DEFAULT_SETTINGS = {
    "ai_provider": "gemini",  # gemini | claude
    "gemini_model": "gemma-3-27b-it",
    "claude_model": "haiku",
}

# In-memory кеш настроек
_settings_cache: dict[str, str] = {}
_cache_loaded: bool = False


async def load_settings_to_cache():
    """Загружает все настройки из БД в кеш (вызывается при старте)"""
    global _settings_cache, _cache_loaded

    async with get_async_session()() as session:
        result = await session.execute(select(AppSettings))
        db_settings = result.scalars().all()

        # Начинаем с дефолтов
        _settings_cache = DEFAULT_SETTINGS.copy()

        # Перезаписываем значениями из БД
        for setting in db_settings:
            _settings_cache[setting.key] = setting.value

        _cache_loaded = True
        logger.info(f"Loaded {len(db_settings)} settings from DB, {len(_settings_cache)} total in cache")


async def ensure_cache_loaded():
    """Убеждается что кеш загружен"""
    if not _cache_loaded:
        await load_settings_to_cache()


def get_setting(key: str, default: str | None = None) -> str | None:
    """
    Получает настройку из кеша (синхронно, быстро).

    Использовать после ensure_cache_loaded() или в контексте где кеш уже загружен.
    """
    if not _cache_loaded:
        # Fallback на дефолты если кеш не загружен
        return DEFAULT_SETTINGS.get(key, default)

    return _settings_cache.get(key, default)


async def get_setting_async(key: str, default: str | None = None) -> str | None:
    """Получает настройку (асинхронно, гарантирует загрузку кеша)"""
    await ensure_cache_loaded()
    return _settings_cache.get(key, default)


async def set_setting(key: str, value: str) -> None:
    """
    Устанавливает настройку в БД и обновляет кеш.
    """
    global _settings_cache

    async with get_async_session()() as session:
        # Ищем существующую настройку
        result = await session.execute(
            select(AppSettings).where(AppSettings.key == key)
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = value
            setting.updated_at = datetime.utcnow()
        else:
            setting = AppSettings(key=key, value=value)
            session.add(setting)

        await session.commit()

    # Обновляем кеш
    _settings_cache[key] = value
    logger.info(f"Setting updated: {key}={value[:50]}{'...' if len(value) > 50 else ''}")


async def get_all_settings() -> dict[str, Any]:
    """Возвращает все настройки"""
    await ensure_cache_loaded()
    return _settings_cache.copy()


async def get_ai_settings() -> dict[str, Any]:
    """Возвращает настройки AI"""
    await ensure_cache_loaded()
    return {
        "provider": _settings_cache.get("ai_provider", "gemini"),
        "gemini_model": _settings_cache.get("gemini_model", "gemma-3-27b-it"),
        "claude_model": _settings_cache.get("claude_model", "haiku"),
    }


# Быстрый доступ к модели для Summarizer
def get_current_model() -> str:
    """Возвращает текущую модель для суммаризации (синхронно)"""
    provider = _settings_cache.get("ai_provider", "gemini")

    if provider == "gemini":
        return _settings_cache.get("gemini_model", "gemma-3-27b-it")
    else:
        return _settings_cache.get("claude_model", "haiku")


def get_current_provider() -> str:
    """Возвращает текущий провайдер (gemini или claude)"""
    return _settings_cache.get("ai_provider", "gemini")
