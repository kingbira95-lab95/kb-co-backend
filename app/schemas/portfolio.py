from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class HoldingCreate(BaseModel):
    symbol: str
    shares: float
    buy_price: float
    buy_date: str
    notes: Optional[str] = None


class HoldingOut(BaseModel):
    id: str
    symbol: str
    shares: float
    buy_price: float
    buy_date: str
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class PortfolioCreate(BaseModel):
    name: str
    description: Optional[str] = None


class PortfolioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class PortfolioOut(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]
    holdings: List[HoldingOut] = []
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class WatchlistItemCreate(BaseModel):
    symbol: str
    price_alert: Optional[float] = None


class WatchlistItemOut(BaseModel):
    id: str
    symbol: str
    price_alert: Optional[float]
    added_at: datetime

    class Config:
        from_attributes = True
