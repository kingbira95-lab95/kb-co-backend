"""
Stocks router.

GET /stocks                   — all cached stocks (with live prices if scraper ran)
GET /stocks/live              — trigger immediate NGX scrape and return fresh data
GET /stocks/summary           — NGX ASI market summary
GET /stocks/gainers           — top 10 gainers
GET /stocks/losers            — top 10 losers
GET /stocks/screener          — filtered/sorted
GET /stocks/ngx-profile/{sym} — proxy NGX company profile (avoids browser CORS)
GET /stocks/{symbol}          — single stock detail from cache
SSE /stocks/stream            — live price stream (Server-Sent Events)
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc, text

from app.database import get_db
from app.models.stock import StockCache, MarketSummaryCache
from app.schemas.stock import StockOut, MarketSummaryOut
from app.services.ngx_scraper import run_scraper_once, get_cached_stocks, get_cached_stock
from app.data.static_stocks import STATIC_STOCKS  # fallback static data

router = APIRouter(prefix="/stocks", tags=["stocks"])


def _stock_to_dict(s: StockCache) -> dict:
    return {
        "symbol": s.symbol,
        "name": s.name,
        "sector": s.sector,
        "price": s.price,
        "prev_close": s.prev_close,
        "change": s.change,
        "change_pct": s.change_pct,
        "open_price": s.open_price,
        "high": s.high,
        "low": s.low,
        "volume": s.volume,
        "market_cap": s.market_cap,
        "pe_ratio": s.pe_ratio,
        "eps": s.eps,
        "dividend_yield": s.dividend_yield,
        "dividend_per_share": s.dividend_per_share,
        "high_52w": s.high_52w,
        "low_52w": s.low_52w,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("", response_model=List[StockOut])
async def list_stocks(
    sector: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stocks = await get_cached_stocks(db)
    if not stocks:
        # Return static fallback if scraper hasn't run yet
        return STATIC_STOCKS
    if sector:
        stocks = [s for s in stocks if s.sector and sector.lower() in s.sector.lower()]
    return stocks


@router.get("/live")
async def live_refresh(db: AsyncSession = Depends(get_db)):
    """Trigger an immediate NGX scrape and refresh the cache."""
    count = await run_scraper_once()
    stocks = await get_cached_stocks(db)
    return {"refreshed": count, "stocks": [_stock_to_dict(s) for s in stocks]}


@router.get("/summary", response_model=MarketSummaryOut)
async def market_summary(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MarketSummaryCache).where(MarketSummaryCache.id == 1))
    summary = result.scalar_one_or_none()
    if not summary:
        # Return computed summary from stock cache
        stocks = await get_cached_stocks(db)
        advances = sum(1 for s in stocks if s.change_pct > 0)
        declines = sum(1 for s in stocks if s.change_pct < 0)
        unchanged = sum(1 for s in stocks if s.change_pct == 0)
        return {
            "asi_value": None, "asi_change": None, "asi_change_pct": None,
            "total_volume": sum(s.volume for s in stocks),
            "total_market_cap": sum(s.market_cap or 0 for s in stocks),
            "advances": advances, "declines": declines, "unchanged": unchanged,
            "updated_at": None,
        }
    return summary


@router.get("/gainers")
async def top_gainers(limit: int = Query(10, le=50), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StockCache).where(StockCache.change_pct > 0).order_by(desc(StockCache.change_pct)).limit(limit)
    )
    stocks = result.scalars().all()
    if not stocks:
        return sorted(STATIC_STOCKS, key=lambda s: s.get("change_pct", 0), reverse=True)[:limit]
    return [_stock_to_dict(s) for s in stocks]


@router.get("/losers")
async def top_losers(limit: int = Query(10, le=50), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StockCache).where(StockCache.change_pct < 0).order_by(asc(StockCache.change_pct)).limit(limit)
    )
    stocks = result.scalars().all()
    if not stocks:
        return sorted(STATIC_STOCKS, key=lambda s: s.get("change_pct", 0))[:limit]
    return [_stock_to_dict(s) for s in stocks]


@router.get("/screener")
async def screener(
    sector: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    min_div_yield: Optional[float] = Query(None),
    sort_by: str = Query("market_cap"),
    sort_dir: str = Query("desc"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    stocks = await get_cached_stocks(db)
    if not stocks:
        stocks_dicts = STATIC_STOCKS
    else:
        stocks_dicts = [_stock_to_dict(s) for s in stocks]

    # Filter
    if sector:
        stocks_dicts = [s for s in stocks_dicts if s.get("sector") and sector.lower() in s["sector"].lower()]
    if min_price is not None:
        stocks_dicts = [s for s in stocks_dicts if s.get("price", 0) >= min_price]
    if max_price is not None:
        stocks_dicts = [s for s in stocks_dicts if s.get("price", 0) <= max_price]
    if min_div_yield is not None:
        stocks_dicts = [s for s in stocks_dicts if (s.get("dividend_yield") or 0) >= min_div_yield]

    # Sort
    reverse = sort_dir.lower() == "desc"
    stocks_dicts.sort(key=lambda s: s.get(sort_by) or 0, reverse=reverse)

    return stocks_dicts[:limit]


@router.get("/stream")
async def price_stream(db: AsyncSession = Depends(get_db)):
    """Server-Sent Events stream — pushes updated prices every 10s."""
    async def event_generator():
        while True:
            stocks = await get_cached_stocks(db)
            data = [{"symbol": s.symbol, "price": s.price, "change": s.change, "change_pct": s.change_pct} for s in stocks]
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(10)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/ngx-profile/{symbol}")
async def ngx_company_profile(symbol: str):
    """Proxy the NGX Group company-profile API to avoid browser CORS restrictions."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    url = (
        f"https://ngxgroup.com/exchange/data/company-profile/"
        f"?symbol={symbol.upper()}&directory=companydirectory&tdate={today}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://ngxgroup.com/",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                try:
                    return r.json()
                except Exception:
                    return {"raw": r.text, "error": "non-JSON response from NGX"}
            return {"error": f"NGX returned HTTP {r.status_code}"}
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/{symbol}", response_model=StockOut)
async def get_stock(symbol: str, db: AsyncSession = Depends(get_db)):
    stock = await get_cached_stock(db, symbol.upper())
    if not stock:
        # Try static fallback
        for s in STATIC_STOCKS:
            if s.get("symbol") == symbol.upper():
                return s
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
    return stock
