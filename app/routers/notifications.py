from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid

from app.database import get_db
from app.models.notification import Notification, NotifTypeEnum
from app.models.user import User
from app.core.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotifOut(BaseModel):
    id: str
    type: str
    title: str
    message: str
    symbol: Optional[str]
    read: bool
    urgent: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[NotifOut])
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read == False)
    query = query.order_by(Notification.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.put("/{notif_id}/read", status_code=204)
async def mark_read(notif_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(update(Notification).where(Notification.id == notif_id, Notification.user_id == user.id).values(read=True))
    await db.commit()


@router.put("/read-all", status_code=204)
async def mark_all_read(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(update(Notification).where(Notification.user_id == user.id).values(read=True))
    await db.commit()


@router.get("/unread-count")
async def unread_count(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Notification).where(Notification.user_id == user.id, Notification.read == False)
    )
    count = len(result.scalars().all())
    return {"count": count}
