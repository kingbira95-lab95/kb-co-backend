from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid

from app.database import get_db
from app.models.portfolio import WatchlistItem
from app.models.user import User
from app.core.deps import get_current_user
from app.schemas.portfolio import WatchlistItemCreate, WatchlistItemOut

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=List[WatchlistItemOut])
async def get_watchlist(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WatchlistItem).where(WatchlistItem.user_id == user.id).order_by(WatchlistItem.added_at.desc()))
    return result.scalars().all()


@router.post("", response_model=WatchlistItemOut, status_code=201)
async def add_to_watchlist(
    body: WatchlistItemCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check if already watched
    result = await db.execute(select(WatchlistItem).where(WatchlistItem.user_id == user.id, WatchlistItem.symbol == body.symbol.upper()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already in watchlist")

    item = WatchlistItem(id=str(uuid.uuid4()), user_id=user.id, symbol=body.symbol.upper(), price_alert=body.price_alert)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{symbol}", status_code=204)
async def remove_from_watchlist(symbol: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WatchlistItem).where(WatchlistItem.user_id == user.id, WatchlistItem.symbol == symbol.upper()))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    await db.delete(item)
    await db.commit()
