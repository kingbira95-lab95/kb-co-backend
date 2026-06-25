"""
Flutterwave payment service.

Handles:
- Initiating payment links for subscription plans
- Verifying completed transactions
- Processing webhooks
- Managing subscription lifecycle
"""
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.subscription import Subscription, Payment, SubStatusEnum, PaymentStatusEnum
from app.models.user import User, PlanEnum
from app.schemas.payment import PLAN_PRICES

FLW_API = settings.FLW_BASE_URL
FLW_HEADERS = {
    "Authorization": f"Bearer {settings.FLW_SECRET_KEY}",
    "Content-Type": "application/json",
}


def make_tx_ref() -> str:
    return f"KBCO-{uuid.uuid4().hex[:16].upper()}"


async def initiate_payment(
    user: User,
    plan: str,
    billing_cycle: str,
    db: AsyncSession,
) -> dict:
    """Create a Flutterwave standard payment link and store a pending payment record."""
    amount = PLAN_PRICES[plan][billing_cycle]
    tx_ref = make_tx_ref()

    # Create pending subscription
    sub = Subscription(
        user_id=user.id,
        plan=plan,
        status=SubStatusEnum.pending,
        amount=amount,
        billing_cycle=billing_cycle,
    )
    db.add(sub)
    await db.flush()

    # Create pending payment
    payment = Payment(
        user_id=user.id,
        subscription_id=sub.id,
        amount=amount,
        currency="NGN",
        status=PaymentStatusEnum.pending,
        tx_ref=tx_ref,
        narration=f"KB & Co {plan.title()} Plan ({billing_cycle})",
        customer_email=user.email,
    )
    db.add(payment)
    await db.commit()

    # Call Flutterwave Standard payment link API
    payload = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": "NGN",
        "redirect_url": f"{settings.FRONTEND_URL}/payment/verify?tx_ref={tx_ref}",
        "customer": {"email": user.email, "name": user.name},
        "customizations": {
            "title": "KB & Co Investment",
            "description": f"{plan.title()} Plan — {billing_cycle}",
            "logo": f"{settings.FRONTEND_URL}/logo.png",
        },
        "meta": {"plan": plan, "user_id": user.id, "subscription_id": sub.id},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{FLW_API}/payments", headers=FLW_HEADERS, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return {
        "payment_link": data["data"]["link"],
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": "NGN",
    }


async def verify_payment(tx_ref: str, transaction_id: str, db: AsyncSession) -> dict:
    """Verify a Flutterwave transaction and activate the subscription on success."""
    # Verify with Flutterwave
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{FLW_API}/transactions/{transaction_id}/verify",
            headers=FLW_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "success" or data["data"]["status"] != "successful":
        return {"success": False, "message": "Transaction not successful"}

    flw_data = data["data"]

    # Find payment record
    result = await db.execute(select(Payment).where(Payment.tx_ref == tx_ref))
    payment = result.scalar_one_or_none()
    if not payment:
        return {"success": False, "message": "Payment record not found"}

    # Guard against replay
    if payment.status == PaymentStatusEnum.successful:
        return {"success": True, "message": "Already processed"}

    # Update payment
    payment.status = PaymentStatusEnum.successful
    payment.flw_tx_id = str(flw_data["id"])
    payment.payment_type = flw_data.get("payment_type")
    payment.verified_at = datetime.now(timezone.utc)

    # Activate subscription
    result2 = await db.execute(select(Subscription).where(Subscription.id == payment.subscription_id))
    sub = result2.scalar_one_or_none()
    if sub:
        now = datetime.now(timezone.utc)
        months = 12 if sub.billing_cycle == "annual" else 1
        sub.status = SubStatusEnum.active
        sub.started_at = now
        sub.expires_at = now + timedelta(days=30 * months)
        sub.flw_subscription_id = flw_data.get("flw_ref")

        # Upgrade user plan
        result3 = await db.execute(select(User).where(User.id == payment.user_id))
        user = result3.scalar_one_or_none()
        if user:
            user.plan = PlanEnum(sub.plan)

    await db.commit()
    return {"success": True, "message": "Subscription activated", "plan": sub.plan if sub else None}


def verify_webhook_signature(payload_body: bytes, signature: str) -> bool:
    """Validate Flutterwave webhook signature."""
    expected = hmac.new(
        settings.FLW_WEBHOOK_SECRET.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def handle_webhook(payload: dict, db: AsyncSession) -> None:
    """Process Flutterwave webhook events."""
    event = payload.get("event")
    data = payload.get("data", {})

    if event == "charge.completed" and data.get("status") == "successful":
        tx_ref = data.get("tx_ref", "")
        flw_tx_id = str(data.get("id", ""))
        if tx_ref.startswith("KBCO-"):
            await verify_payment(tx_ref, flw_tx_id, db)
