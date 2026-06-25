from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from app.database import get_db
from app.models.alert import PriceAlert, AlertDirectionEnum
from app.models.user import User
from app.core.deps import get_current_user

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertCreate(BaseModel):
    symbol: str
    target_price: float
    direction: str  # "above" | "below"
    notify_email: bool = True
    notify_sms: bool = False


class AlertOut(BaseModel):
    id: str
    symbol: str
    target_price: float
    direction: str
    active: bool
    triggered: bool
    triggered_at: Optional[datetime]
    notify_email: bool
    notify_sms: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[AlertOut])
async def list_alerts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PriceAlert).where(PriceAlert.user_id == user.id).order_by(PriceAlert.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=AlertOut, status_code=201)
async def create_alert(body: AlertCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.direction not in ("above", "below"):
        raise HTTPException(status_code=400, detail="direction must be 'above' or 'below'")

    alert = PriceAlert(
        id=str(uuid.uuid4()),
        user_id=user.id,
        symbol=body.symbol.upper(),
        target_price=body.target_price,
        direction=AlertDirectionEnum(body.direction),
        notify_email=body.notify_email,
        notify_sms=body.notify_sms,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


@router.delete("/{alert_id}", status_code=204)
async def delete_alert(alert_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PriceAlert).where(PriceAlert.id == alert_id, PriceAlert.user_id == user.id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
    await db.commit()
