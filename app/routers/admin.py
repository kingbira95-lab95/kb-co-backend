from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone

from app.database import get_db
from app.models.user import User, KYCStatusEnum
from app.models.subscription import Subscription, SubStatusEnum
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
    return [{"id": u.id, "email": u.email, "name": u.name, "plan": u.plan, "kyc_status": u.kyc_status, "is_admin": u.is_admin, "created_at": u.created_at} for u in users]


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
    result = await db.execute(select(User).where(User.is_active == True))
    users = result.scalars().all()

    notifs = [
        Notification(
            id=str(uuid.uuid4()),
            user_id=u.id,
            type=NotifTypeEnum(body.type),
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
