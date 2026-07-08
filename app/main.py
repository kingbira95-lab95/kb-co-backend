"""
KB & Co Corporate Investment Limited — FastAPI Backend
"""
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import settings
from app.database import create_tables, run_migrations
from app.routers import auth, users, stocks, portfolios, watchlist, payments, alerts, notifications, exports, admin, bonds, ai
from app.services.ngx_scraper import run_scraper_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    logger.info("KB & Co backend starting up — environment: %s", settings.ENVIRONMENT)
    logger.info("Database: %s", settings.DATABASE_URL.split("@")[-1])  # log host only, not creds
    await run_migrations()  # runs alembic upgrade head; falls back to create_all

    # Initial NGX scrape on boot
    try:
        count = await run_scraper_once()
        logger.info(f"Initial NGX scrape: {count} stocks")
    except Exception as e:
        logger.warning(f"Initial scrape failed (will retry on schedule): {e}")

    # Schedule periodic NGX scrape
    scheduler.add_job(
        run_scraper_once,
        "interval",
        minutes=30,  # Live prices every 30 min from NGX price list + TradingView Nigeria
        id="ngx_scraper",
        replace_existing=True,
    )

    # Check price alerts every 10 minutes
    scheduler.add_job(
        _check_price_alerts,
        "interval",
        minutes=10,
        id="alert_checker",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started — NGX + TradingView price scrape every 30 min")

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    scheduler.shutdown(wait=False)
    logger.info("KB & Co backend shut down")


async def _check_price_alerts():
    """Check all active price alerts against current stock prices."""
    from app.database import AsyncSessionLocal
    from sqlalchemy import select
    from app.models.alert import PriceAlert, AlertDirectionEnum
    from app.models.stock import StockCache
    from app.models.user import User
    from app.models.notification import Notification, NotifTypeEnum
    from app.services.email_service import send_price_alert
    from app.services.sms_service import send_price_alert_sms
    from datetime import datetime, timezone
    import uuid

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PriceAlert).where(PriceAlert.active == True, PriceAlert.triggered == False))
        alerts = result.scalars().all()

        for alert in alerts:
            stock_r = await db.execute(select(StockCache).where(StockCache.symbol == alert.symbol))
            stock = stock_r.scalar_one_or_none()
            if not stock:
                continue

            triggered = (
                (alert.direction == AlertDirectionEnum.above and stock.price >= alert.target_price) or
                (alert.direction == AlertDirectionEnum.below and stock.price <= alert.target_price)
            )
            if not triggered:
                continue

            # Mark as triggered
            alert.triggered = True
            alert.triggered_at = datetime.now(timezone.utc)

            # Fetch user
            user_r = await db.execute(select(User).where(User.id == alert.user_id))
            user = user_r.scalar_one_or_none()
            if not user:
                continue

            # In-app notification
            db.add(Notification(
                id=str(uuid.uuid4()),
                user_id=user.id,
                type=NotifTypeEnum.alert,
                title=f"Price Alert: {alert.symbol}",
                message=f"{alert.symbol} {'rose above' if alert.direction == AlertDirectionEnum.above else 'fell below'} ₦{alert.target_price:,.2f}. Current: ₦{stock.price:,.2f}",
                symbol=alert.symbol,
                urgent=True,
            ))

            # Email alert
            if alert.notify_email:
                try:
                    await send_price_alert(user.email, user.name, alert.symbol, stock.price, alert.target_price, alert.direction.value)
                except Exception as e:
                    logger.error(f"Email alert error: {e}")

            # SMS alert
            if alert.notify_sms and user.phone:
                try:
                    await send_price_alert_sms(user.phone, alert.symbol, stock.price, alert.direction.value)
                except Exception as e:
                    logger.error(f"SMS alert error: {e}")

        await db.commit()
        if alerts:
            triggered_count = sum(1 for a in alerts if a.triggered)
            logger.info(f"Alert check: {triggered_count}/{len(alerts)} alerts triggered")


app = FastAPI(
    title="KB & Co Corporate Investment API",
    description="Nigeria's premier wealth management and investment intelligence platform API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Middleware ─────────────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=500)
_cors_origins = [
    settings.FRONTEND_URL,
    "http://localhost:3000",
    "http://localhost:5173",
    # Allow any Railway or Vercel preview URL automatically
    "https://*.up.railway.app",
    "https://*.vercel.app",
    "https://*.netlify.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.(up\.railway\.app|vercel\.app|netlify\.app)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(stocks.router)
app.include_router(portfolios.router)
app.include_router(watchlist.router)
app.include_router(payments.router)
app.include_router(alerts.router)
app.include_router(notifications.router)
app.include_router(exports.router)
app.include_router(bonds.router)
app.include_router(ai.router)
app.include_router(admin.router)


@app.get("/")
async def root():
    return {
        "name": "KB & Co Corporate Investment API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "tagline": "Investing In The Future.",
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "environment": settings.ENVIRONMENT}
