import os
from pydantic_settings import BaseSettings
from typing import Literal


def _normalise_db_url(url: str) -> str:
    """
    Railway (and Heroku) provide DATABASE_URL as  postgres://...  or
    postgresql://...  — both of which are the *sync* dialect.  SQLAlchemy
    async needs  postgresql+asyncpg://...   This function patches it up.
    """
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    # Already has a driver prefix — leave it alone
    return url


def _build_db_url() -> str:
    """
    Resolve DATABASE_URL from the environment with Railway fallbacks.

    Priority:
      1. DATABASE_URL env var (Railway PostgreSQL plugin sets this automatically)
      2. Individual PG* vars (also set by Railway: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE)
      3. Local dev default
    """
    raw = os.getenv("DATABASE_URL")
    if raw:
        return _normalise_db_url(raw)

    # Railway also exposes individual PG* variables
    pghost = os.getenv("PGHOST")
    pgport = os.getenv("PGPORT", "5432")
    pguser = os.getenv("PGUSER", "postgres")
    pgpass = os.getenv("PGPASSWORD", "")
    pgdb   = os.getenv("PGDATABASE", "railway")

    if pghost:
        return f"postgresql+asyncpg://{pguser}:{pgpass}@{pghost}:{pgport}/{pgdb}"

    # Local development fallback
    return "postgresql+asyncpg://postgres:password@localhost:5432/kbco"


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────────────────
    # Pydantic reads DATABASE_URL from env; we then normalise it in model_post_init.
    DATABASE_URL: str = _build_db_url()

    # Railway sets PORT automatically; default to 8000 for local dev
    PORT: int = int(os.getenv("PORT", "8000"))

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── Google OAuth ──────────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"

    # ── Flutterwave ───────────────────────────────────────────────────────────
    FLW_PUBLIC_KEY: str = ""
    FLW_SECRET_KEY: str = ""
    FLW_WEBHOOK_SECRET: str = ""
    FLW_BASE_URL: str = "https://api.flutterwave.com/v3"

    # ── Termii SMS ────────────────────────────────────────────────────────────
    TERMII_API_KEY: str = ""
    TERMII_SENDER_ID: str = "KB-Co"
    TERMII_BASE_URL: str = "https://api.ng.termii.com/api"

    # ── Email (SMTP) ──────────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM_NAME: str = "KB & Co Investment"
    EMAIL_FROM: str = "noreply@kbco.invest"

    # ── OpenRouter AI ─────────────────────────────────────────────────────────
    OPENROUTER_API_KEY: str = ""  # Set via OPENROUTER_API_KEY env var / Railway dashboard
    OPENROUTER_MODEL: str = "openai/gpt-oss-120b:free"

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "KB & Co Corporate Investment Limited"
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")
    ENVIRONMENT: Literal["development", "staging", "production"] = (
        "production" if os.getenv("RAILWAY_ENVIRONMENT") else "development"
    )
    NGX_SCRAPE_INTERVAL_MINUTES: int = 1440  # 24 h; override in Railway env vars

    # ── Redis (optional) ─────────────────────────────────────────────────────
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    def model_post_init(self, __context: object) -> None:
        """Normalise DATABASE_URL after pydantic reads it from the environment."""
        if self.DATABASE_URL:
            object.__setattr__(self, "DATABASE_URL", _normalise_db_url(self.DATABASE_URL))

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
