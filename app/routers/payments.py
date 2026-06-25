"""Flutterwave payment & subscription router."""
import json
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.database import get_db
from app.models.user import User
from app.models.subscription import Subscription, Payment
from app.core.deps import get_current_user
from app.schemas.payment import PaymentInitRequest, PaymentInitResponse, PaymentVerifyRequest, PaymentOut, SubscriptionOut
from app.services.flutterwave import initiate_payment, verify_payment, verify_webhook_signature, handle_webhook
from app.services.email_service import send_subscription_confirmation
from app.services.sms_service import send_payment_sms
from app.config import settings

router = APIRouter(prefix="/payments", tags=["payments"])

PLANS = {
    "free": {"name": "Free", "price_monthly": 0, "price_annual": 0, "features": ["Basic stock data", "5-stock watchlist", "Market news"]},
    "premium": {"name": "Premium", "price_monthly": 2500, "price_annual": 25000, "features": ["Full NGX data", "AI Advisor", "Dividend alerts", "Portfolio tracker", "Excel export"]},
    "elite": {"name": "Elite", "price_monthly": 5000, "price_annual": 50000, "features": ["Everything in Premium", "Trading account", "SMS alerts", "Priority support", "PDF reports", "Unlimited watchlist"]},
}


@router.get("/plans")
async def get_plans():
    return PLANS


@router.post("/initiate", response_model=PaymentInitResponse)
async def initiate(
    body: PaymentInitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.plan not in ("premium", "elite"):
        raise HTTPException(status_code=400, detail="Invalid plan")
    if body.billing_cycle not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="Invalid billing cycle")

    if not settings.FLW_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")

    result = await initiate_payment(user, body.plan, body.billing_cycle, db)
    return result


@router.post("/verify")
async def verify(
    body: PaymentVerifyRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await verify_payment(body.tx_ref, body.transaction_id, db)
    if result.get("success") and result.get("plan"):
        # Send notifications in background
        plan = result["plan"]
        background_tasks.add_task(send_subscription_confirmation, user.email, user.name, plan, "Next 30 days")
        if user.phone:
            from app.schemas.payment import PLAN_PRICES
            background_tasks.add_task(send_payment_sms, user.phone, plan, PLAN_PRICES[plan]["monthly"])
    return result


@router.post("/webhook")
async def flutterwave_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Flutterwave will POST events here. Verify signature before processing."""
    body_bytes = await request.body()
    signature = request.headers.get("verif-hash", "")

    if settings.FLW_WEBHOOK_SECRET and not verify_webhook_signature(body_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    await handle_webhook(payload, db)
    return {"status": "ok"}


@router.get("/history", response_model=List[PaymentOut])
async def payment_history(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Payment).where(Payment.user_id == user.id).order_by(Payment.created_at.desc()))
    return result.scalars().all()


@router.get("/subscription", response_model=SubscriptionOut)
async def current_subscription(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")
    return sub
