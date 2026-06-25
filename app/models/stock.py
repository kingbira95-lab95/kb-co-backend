from sqlalchemy import Column, String, Float, Integer, DateTime, Text, Boolean
from sqlalchemy.sql import func
from app.database import Base


class StockCache(Base):
    """Live NGX stock data cache — refreshed every 5 minutes by the scraper."""
    __tablename__ = "stock_cache"

    symbol = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    sector = Column(String, nullable=True)
    price = Column(Float, nullable=False, default=0)
    prev_close = Column(Float, nullable=True)
    change = Column(Float, default=0)
    change_pct = Column(Float, default=0)
    open_price = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    volume = Column(Float, default=0)
    market_cap = Column(Float, nullable=True)
    pe_ratio = Column(Float, nullable=True)
    eps = Column(Float, nullable=True)
    dividend_yield = Column(Float, nullable=True)
    dividend_per_share = Column(Float, nullable=True)
    high_52w = Column(Float, nullable=True)
    low_52w = Column(Float, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MarketSummaryCache(Base):
    """NGX ASI and market-wide stats."""
    __tablename__ = "market_summary_cache"

    id = Column(Integer, primary_key=True, default=1)
    asi_value = Column(Float, nullable=True)
    asi_change = Column(Float, nullable=True)
    asi_change_pct = Column(Float, nullable=True)
    total_volume = Column(Float, nullable=True)
    total_market_cap = Column(Float, nullable=True)
    advances = Column(Integer, nullable=True)
    declines = Column(Integer, nullable=True)
    unchanged = Column(Integer, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
