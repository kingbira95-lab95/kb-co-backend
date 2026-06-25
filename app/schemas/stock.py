from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class StockOut(BaseModel):
    symbol: str
    name: str
    sector: Optional[str]
    price: float
    prev_close: Optional[float]
    change: float
    change_pct: float
    open_price: Optional[float]
    high: Optional[float]
    low: Optional[float]
    volume: float
    market_cap: Optional[float]
    pe_ratio: Optional[float]
    eps: Optional[float]
    dividend_yield: Optional[float]
    dividend_per_share: Optional[float]
    high_52w: Optional[float]
    low_52w: Optional[float]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class MarketSummaryOut(BaseModel):
    asi_value: Optional[float]
    asi_change: Optional[float]
    asi_change_pct: Optional[float]
    total_volume: Optional[float]
    total_market_cap: Optional[float]
    advances: Optional[int]
    declines: Optional[int]
    unchanged: Optional[int]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class ScreenerQuery(BaseModel):
    sector: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_market_cap: Optional[float] = None
    min_dividend_yield: Optional[float] = None
    sort_by: str = "market_cap"
    sort_dir: str = "desc"
    limit: int = 50
