import os
import ssl
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

logger = logging.getLogger(__name__)

# ── SSL ───────────────────────────────────────────────────────────────────────
# Railway's managed PostgreSQL requires SSL in production.
# asyncpg accepts an ssl context (or the string "require") via connect_args.

_connect_args: dict = {}
if settings.ENVIRONMENT == "production":
    # Create a permissive SSL context — Railway uses self-signed or internal CA certs
    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE
    _connect_args["ssl"] = _ssl_ctx

# ── Engine ────────────────────────────────────────────────────────────────────
# Railway free tier PostgreSQL limits total connections; keep the pool small.
_is_prod = settings.ENVIRONMENT == "production"

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=not _is_prod,                     # SQL logging only in dev
    pool_size=5 if _is_prod else 10,       # stay inside Railway connection limits
    max_overflow=10 if _is_prod else 20,
    pool_timeout=30,
    pool_recycle=1800,                     # recycle connections every 30 min
    pool_pre_ping=True,                    # detect stale connections
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_tables():
    """Create all tables that don't yet exist (idempotent — safe to call on every boot)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created / verified OK")


async def run_migrations():
    """
    Run Alembic migrations programmatically on startup.
    Falls back to create_tables() if Alembic is not available or has no migrations.
    """
    try:
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            logger.info("Alembic migrations applied: %s", result.stdout.strip() or "up to date")
        else:
            logger.warning("Alembic migration warning: %s — falling back to create_all", result.stderr.strip())
            await create_tables()
    except Exception as exc:
        logger.warning("Could not run Alembic (%s) — using create_all fallback", exc)
        await create_tables()
