from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import os

# Lazy initialization
_engine = None
_async_session = None


def get_database_url() -> str:
    """Get and format DATABASE_URL"""
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL environment variable is not set")

    # Railway даёт postgres://, но asyncpg требует postgresql+asyncpg://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return url


def get_engine():
    """Lazy engine initialization"""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_database_url(),
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def get_async_session():
    """Lazy session factory initialization"""
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session


# Aliases for compatibility
@property
def engine():
    return get_engine()


@property
def async_session():
    return get_async_session()


class Base(DeclarativeBase):
    pass


async def init_db():
    """Создаёт все таблицы"""
    from app.db.models import User, Channel, Subscription, Post  # noqa
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Dependency для FastAPI"""
    session_factory = get_async_session()
    async with session_factory() as session:
        yield session
