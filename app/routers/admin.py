from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone

from app.database import get_db
from app.models.user import User, KYCStatusEnum, PlanEnum
from app.models.subscription import Subscription, SubStatusEnum, Payment, PaymentStatusEnum
from app.models.notification import Notification, NotifTypeEnum
from app.core.deps import get_current_admin
from app.services.email_service import send_kyc_update
from app.services.sms_service import send_kyc_sms
import uuid

router = APIRouter(prefix="/admin", tags=["admin"])


class BroadcastRequest(BaseModel):
    title: str
    message: str
    type: str = "system"


class KYCDecisionRequest(BaseModel):
    status: str  # "verified" | "rejected"
    reason: Optional[str] = None


class PlanUpdateRequest(BaseModel):
    plan: str  # "free" | "premium" | "elite"


class PaymentStatusRequest(BaseModel):
    status: str  # "successful" | "failed" | "refunded"


@router.get("/stats")
async def platform_stats(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    total_users = (await db.execute(select(func.count(User.id)))).scalar()
    active_subs = (await db.execute(select(func.count(Subscription.id)).where(Subscription.status == SubStatusEnum.active))).scalar()
    kyc_pending = (await db.execute(select(func.count(User.id)).where(User.kyc_status == KYCStatusEnum.submitted))).scalar()

    from app.models.stock import StockCache
    total_stocks = (await db.execute(select(func.count(StockCache.symbol)))).scalar()

    from app.models.subscription import Payment, PaymentStatusEnum
    total_revenue = (await db.execute(
        select(func.sum(Payment.amount)).where(Payment.status == PaymentStatusEnum.successful)
    )).scalar() or 0

    return {
        "total_users": total_users,
        "active_subscriptions": active_subs,
        "kyc_pending": kyc_pending,
        "total_stocks": total_stocks,
        "total_revenue_ngn": total_revenue,
    }


@router.get("/users")
async def list_users(
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    if search:
        query = query.where(User.email.ilike(f"%{search}%") | User.name.ilike(f"%{search}%"))
    result = await db.execute(query)
    users = result.scalars().all()
    return [
        {
            "id": u.id, "email": u.email, "name": u.name, "plan": u.plan,
            "kyc_status": u.kyc_status, "is_admin": u.is_admin,
            "is_active": u.is_active, "phone": u.phone, "created_at": u.created_at,
        }
        for u in users
    ]


@router.get("/users/{user_id}/kyc")
async def get_user_kyc(user_id: str, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Full KYC document for admin review before approving."""
    from app.models.user import KYCDocument
    result = await db.execute(select(KYCDocument).where(KYCDocument.user_id == user_id))
    kyc = result.scalar_one_or_none()
    if not kyc:
        raise HTTPException(status_code=404, detail="No KYC submission for this user")
    return {
        "user_id": kyc.user_id, "bvn": kyc.bvn, "nin": kyc.nin,
        "address": kyc.address, "city": kyc.city, "state": kyc.state,
        "bank_name": kyc.bank_name, "account_number": kyc.account_number,
        "account_name": kyc.account_name, "id_type": kyc.id_type, "id_number": kyc.id_number,
        "status": kyc.status, "submitted_at": kyc.submitted_at,
        "reviewed_at": kyc.reviewed_at, "rejection_reason": kyc.rejection_reason,
    }


@router.put("/users/{user_id}/plan")
async def set_user_plan(
    user_id: str,
    body: PlanUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually verify/assign a subscription plan for a user."""
    if body.plan not in ("free", "premium", "elite"):
        raise HTTPException(status_code=400, detail="plan must be free, premium or elite")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.plan = PlanEnum(body.plan)
    db.add(Notification(
        id=str(uuid.uuid4()), user_id=user.id, type=NotifTypeEnum.system,
        title="Subscription Updated",
        message=f"Your plan has been set to {body.plan.capitalize()} by KB & Co admin.",
    ))
    await db.commit()
    return {"status": "updated", "user_id": user_id, "plan": body.plan}


@router.put("/users/{user_id}/toggle-active")
async def toggle_user_active(user_id: str, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Approve (activate) or suspend a user account."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot suspend an admin account")
    user.is_active = not user.is_active
    await db.commit()
    return {"user_id": user_id, "is_active": user.is_active}


@router.get("/payments")
async def list_payments(
    limit: int = 100,
    status_filter: Optional[str] = None,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """All platform payments — subscriptions and trading account deposits."""
    query = select(Payment).order_by(Payment.created_at.desc()).limit(limit)
    if status_filter:
        query = query.where(Payment.status == PaymentStatusEnum(status_filter))
    result = await db.execute(query)
    payments = result.scalars().all()
    return [
        {
            "id": p.id, "user_id": p.user_id, "amount": p.amount, "currency": p.currency,
            "status": p.status, "tx_ref": p.tx_ref, "payment_type": p.payment_type,
            "narration": p.narration, "customer_email": p.customer_email,
            "created_at": p.created_at, "verified_at": p.verified_at,
        }
        for p in payments
    ]


@router.put("/payments/{payment_id}/status")
async def update_payment_status(
    payment_id: str,
    body: PaymentStatusRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually verify, fail, or refund a payment/payout."""
    if body.status not in ("successful", "failed", "refunded"):
        raise HTTPException(status_code=400, detail="status must be successful, failed or refunded")
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment.status = PaymentStatusEnum(body.status)
    if body.status == "successful":
        payment.verified_at = datetime.now(timezone.utc)
    await db.commit()
    return {"payment_id": payment_id, "status": body.status}


@router.post("/stocks/refresh")
async def admin_refresh_stocks(admin: User = Depends(get_current_admin)):
    """Trigger an immediate NGX price scrape."""
    from app.services.ngx_scraper import run_scraper_once
    count = await run_scraper_once()
    return {"refreshed": count}


@router.put("/users/{user_id}/kyc")
async def admin_kyc_decision(
    user_id: str,
    body: KYCDecisionRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.status not in ("verified", "rejected"):
        raise HTTPException(status_code=400, detail="status must be verified or rejected")

    user.kyc_status = KYCStatusEnum(body.status)

    if user.kyc:
        user.kyc.status = KYCStatusEnum(body.status)
        user.kyc.reviewed_at = datetime.now(timezone.utc)
        user.kyc.rejection_reason = body.reason

    await db.commit()

    # Notify user
    try:
        await send_kyc_update(user.email, user.name, body.status, body.reason)
        if user.phone:
            await send_kyc_sms(user.phone, body.status)
    except Exception:
        pass

    return {"status": "updated", "user_id": user_id, "kyc_status": body.status}


@router.post("/broadcast")
async def broadcast_notification(
    body: BroadcastRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send a notification to all active users."""
    # Map friendly frontend types onto the notification enum so a bad
    # type never 500s the whole broadcast (e.g. "market" -> news).
    try:
        notif_type = NotifTypeEnum(body.type)
    except ValueError:
        notif_type = {"market": NotifTypeEnum.news, "report": NotifTypeEnum.news}.get(
            body.type, NotifTypeEnum.system
        )

    result = await db.execute(select(User).where(User.is_active == True))
    users = result.scalars().all()

    notifs = [
        Notification(
            id=str(uuid.uuid4()),
            user_id=u.id,
            type=notif_type,
            title=body.title,
            message=body.message,
        )
        for u in users
    ]
    db.add_all(notifs)
    await db.commit()
    return {"sent": len(notifs)}


@router.put("/users/{user_id}/toggle-admin")
async def toggle_admin(user_id: str, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = not user.is_admin
    await db.commit()
    return {"is_admin": user.is_admin}
