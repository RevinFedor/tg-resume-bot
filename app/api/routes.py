import os
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from typing import Optional

from app.db.database import get_async_session
from app.db.models import User, Channel, Subscription, Post
from app.services.userbot import get_userbot_service, AuthState
from app.services import settings as app_settings

router = APIRouter(prefix="/api", tags=["api"])


# Pydantic models
class StatsResponse(BaseModel):
    total_users: int
    total_channels: int
    total_subscriptions: int
    total_posts: int


class ChannelUpdate(BaseModel):
    is_active: bool | None = None


# Userbot models
class UserbotPhoneRequest(BaseModel):
    phone_number: str


class UserbotCodeRequest(BaseModel):
    code: str


class UserbotPasswordRequest(BaseModel):
    password: str


class UserbotJoinChannelRequest(BaseModel):
    username: str


# AI Settings models
class AISettingsUpdate(BaseModel):
    provider: Optional[str] = None  # gemini | claude
    gemini_model: Optional[str] = None
    claude_model: Optional[str] = None


class AIStatusResponse(BaseModel):
    provider: str
    model: str
    status: str  # ok | rate_limited | error
    message: Optional[str] = None


# Dependency
async def get_db():
    async with get_async_session()() as session:
        yield session


@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get dashboard statistics"""
    users = await db.execute(select(func.count(User.id)))
    channels = await db.execute(select(func.count(Channel.id)))
    subscriptions = await db.execute(select(func.count(Subscription.id)))
    posts = await db.execute(select(func.count(Post.id)))

    return StatsResponse(
        total_users=users.scalar() or 0,
        total_channels=channels.scalar() or 0,
        total_subscriptions=subscriptions.scalar() or 0,
        total_posts=posts.scalar() or 0,
    )


@router.get("/users")
async def get_users(db: AsyncSession = Depends(get_db)):
    """Get all users"""
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "telegram_id": u.telegram_id,
            "username": u.username,
            "first_name": u.first_name,
            "is_admin": u.is_admin,
            "interests": u.interests,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a user"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()
    return {"status": "deleted"}


@router.get("/channels")
async def get_channels(db: AsyncSession = Depends(get_db)):
    """Get all channels"""
    result = await db.execute(
        select(Channel).order_by(Channel.created_at.desc())
    )
    channels = result.scalars().all()
    return [
        {
            "id": c.id,
            "username": c.username,
            "title": c.title,
            "last_post_id": c.last_post_id,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat(),
            "last_checked_at": c.last_checked_at.isoformat() if c.last_checked_at else None,
        }
        for c in channels
    ]


@router.patch("/channels/{channel_id}")
async def update_channel(
    channel_id: int,
    data: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update channel (toggle active status)"""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if data.is_active is not None:
        channel.is_active = data.is_active

    await db.commit()
    return {"status": "updated"}


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a channel"""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    await db.delete(channel)
    await db.commit()
    return {"status": "deleted"}


@router.get("/subscriptions")
async def get_subscriptions(db: AsyncSession = Depends(get_db)):
    """Get all subscriptions with user and channel info"""
    result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.user), selectinload(Subscription.channel))
        .order_by(Subscription.created_at.desc())
    )
    subscriptions = result.scalars().all()
    return [
        {
            "id": s.id,
            "user_id": s.user_id,
            "channel_id": s.channel_id,
            "created_at": s.created_at.isoformat(),
            "user": {
                "id": s.user.id,
                "telegram_id": s.user.telegram_id,
                "username": s.user.username,
            } if s.user else None,
            "channel": {
                "id": s.channel.id,
                "username": s.channel.username,
                "title": s.channel.title,
            } if s.channel else None,
        }
        for s in subscriptions
    ]


@router.get("/posts")
async def get_posts(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Get recent posts with summaries"""
    result = await db.execute(
        select(Post)
        .options(selectinload(Post.channel))
        .order_by(Post.created_at.desc())
        .limit(limit)
    )
    posts = result.scalars().all()
    return [
        {
            "id": p.id,
            "channel_id": p.channel_id,
            "post_id": p.post_id,
            "content": p.content[:500] + "..." if p.content and len(p.content) > 500 else p.content,
            "summary": p.summary,
            "created_at": p.created_at.isoformat(),
            "channel": {
                "id": p.channel.id,
                "username": p.channel.username,
                "title": p.channel.title,
            } if p.channel else None,
        }
        for p in posts
    ]


# =============================================================================
# USERBOT ENDPOINTS
# =============================================================================

@router.get("/userbot/status")
async def get_userbot_status():
    """
    Получить статус userbot.

    Возвращает:
    - configured: настроены ли API credentials
    - state: текущее состояние авторизации
    - phone: номер телефона (если авторизован)
    - message: описание текущего состояния
    """
    userbot = get_userbot_service()
    return await userbot.get_status()


@router.post("/userbot/start")
async def start_userbot_auth(data: UserbotPhoneRequest):
    """
    Начать авторизацию userbot.

    Отправляет код подтверждения на указанный номер телефона.

    Args:
        phone_number: Номер в международном формате (+7...)
    """
    userbot = get_userbot_service()
    result = await userbot.start_auth(data.phone_number)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


@router.post("/userbot/code")
async def confirm_userbot_code(data: UserbotCodeRequest):
    """
    Подтвердить код из Telegram.

    Args:
        code: 5-значный код из SMS или Telegram
    """
    userbot = get_userbot_service()
    result = await userbot.confirm_code(data.code)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


@router.post("/userbot/password")
async def confirm_userbot_password(data: UserbotPasswordRequest):
    """
    Подтвердить пароль 2FA.

    Args:
        password: Пароль двухфакторной аутентификации
    """
    userbot = get_userbot_service()
    result = await userbot.confirm_password(data.password)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


@router.post("/userbot/logout")
async def logout_userbot():
    """Выйти из аккаунта userbot"""
    userbot = get_userbot_service()
    result = await userbot.logout()

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


@router.post("/userbot/join")
async def userbot_join_channel(data: UserbotJoinChannelRequest):
    """
    Подписать userbot на канал.

    Это нужно для получения голосовых и видео из канала.

    Args:
        username: Username канала (без @)
    """
    userbot = get_userbot_service()
    result = await userbot.join_channel(data.username)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


@router.get("/userbot/channels/{username}/messages")
async def get_channel_messages_via_userbot(
    username: str,
    after_id: int = 0,
    limit: int = 10,
):
    """
    Получить сообщения из канала через userbot.

    Позволяет получать информацию о голосовых и видео.

    Args:
        username: Username канала
        after_id: Получать сообщения после этого ID
        limit: Максимальное количество сообщений
    """
    userbot = get_userbot_service()
    messages = await userbot.get_channel_messages(username, after_id, limit)

    return {
        "channel": username,
        "messages": messages,
        "count": len(messages),
    }


# =============================================================================
# AI SETTINGS ENDPOINTS
# =============================================================================

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _probe_gemini_model(api_key: str, model: str) -> dict:
    """Проверяет доступность модели Gemini"""
    url = f"{GEMINI_BASE_URL}/models/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [{"parts": [{"text": "1"}]}],
        "generationConfig": {"maxOutputTokens": 1}
    }

    try:
        req = Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urlopen(req, timeout=15) as resp:
            return {"status": "ok"}
    except HTTPError as e:
        if e.code == 429:
            return {"status": "rate_limited", "message": "Лимит исчерпан"}
        else:
            error_body = e.read().decode()
            return {"status": "error", "message": f"Error {e.code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/ai/settings")
async def get_ai_settings():
    """Получить текущие настройки AI"""
    settings = await app_settings.get_ai_settings()
    return settings


@router.put("/ai/settings")
async def update_ai_settings(data: AISettingsUpdate):
    """Обновить настройки AI"""
    if data.provider is not None:
        if data.provider not in ("gemini", "claude"):
            raise HTTPException(status_code=400, detail="Invalid provider. Use 'gemini' or 'claude'")
        await app_settings.set_setting("ai_provider", data.provider)

    if data.gemini_model is not None:
        await app_settings.set_setting("gemini_model", data.gemini_model)

    if data.claude_model is not None:
        await app_settings.set_setting("claude_model", data.claude_model)

    return await app_settings.get_ai_settings()


@router.get("/ai/status")
async def get_ai_status():
    """
    Проверяет статус текущей AI модели.

    Делает минимальный probe запрос чтобы определить:
    - ok: модель работает
    - rate_limited: лимит исчерпан
    - error: ошибка
    """
    settings = await app_settings.get_ai_settings()
    provider = settings["provider"]

    if provider == "gemini":
        model = settings["gemini_model"]
        api_key = os.getenv("GEMINI_API_KEY", "")

        if not api_key:
            return AIStatusResponse(
                provider=provider,
                model=model,
                status="error",
                message="GEMINI_API_KEY не настроен"
            )

        result = _probe_gemini_model(api_key, model)

        return AIStatusResponse(
            provider=provider,
            model=model,
            status=result["status"],
            message=result.get("message")
        )
    else:
        # Claude - пока не реализовано
        return AIStatusResponse(
            provider=provider,
            model=settings["claude_model"],
            status="ok",
            message="Claude проверка не реализована"
        )


@router.get("/ai/models")
async def get_available_models():
    """
    Получить список доступных моделей Gemini.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")

    if not api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY не настроен")

    try:
        url = f"{GEMINI_BASE_URL}/models?key={api_key}"
        req = Request(url)
        with urlopen(req, timeout=15) as resp:
            data = json.load(resp)

        models = []
        for m in data.get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                models.append({
                    "name": m.get("name", "").replace("models/", ""),
                    "displayName": m.get("displayName", ""),
                    "inputTokenLimit": m.get("inputTokenLimit"),
                    "outputTokenLimit": m.get("outputTokenLimit"),
                })

        return {
            "models": models,
            "count": len(models)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
