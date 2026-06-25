"""
NGX live price scraper.

Primary source  : TradingView Nigeria screener API (price, PE, EPS, market-cap, 52w H/L, div yield)
Secondary source: NGX Group equities price list (official closing prices)

Merges both sources — TradingView for richer metrics, NGX for official close confirmation.
Updates the stock_cache table every NGX_SCRAPE_INTERVAL_MINUTES minutes (default 1440 = 24 h).
"""
import asyncio
import logging
from typing import Optional
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models.stock import StockCache, MarketSummaryCache
from app.config import settings

logger = logging.getLogger(__name__)

# ── Sources ────────────────────────────────────────────────────────────────────

NGX_URL = "https://ngxgroup.com/exchange/data/equities-price-list/"

TV_SCREENER_URL = "https://scanner.tradingview.com/nigeria/scan"

TV_COLUMNS = [
    "name",                          # 0  ticker symbol
    "description",                   # 1  full company name
    "close",                         # 2  last close price
    "change",                        # 3  % change
    "change_abs",                    # 4  absolute change
    "volume",                        # 5  volume
    "market_cap_basic",              # 6  market cap
    "earnings_per_share_basic_ttm",  # 7  EPS TTM
    "price_earnings_ttm",            # 8  P/E TTM
    "dividends_yield_current",       # 9  dividend yield %
    "52_week_high",                  # 10 52-week high
    "52_week_low",                   # 11 52-week low
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

TV_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}

# Sector map for symbols whose sector TradingView may not return
SECTOR_MAP: dict[str, str] = {
    "DANGCEM": "Building Materials", "BUACEMENT": "Building Materials", "WAPCO": "Building Materials",
    "BUAFOODS": "Consumer Goods", "NESTLE": "Consumer Goods", "FLOURMILL": "Consumer Goods",
    "DANGSUGAR": "Consumer Goods", "GUINNESS": "Consumer Goods", "NB": "Consumer Goods",
    "NASCON": "Consumer Goods", "BETAGLAS": "Consumer Goods",
    "MTNN": "Telecommunications", "AIRTELAFRI": "Telecommunications",
    "ZENITHBANK": "Banking", "GTCO": "Banking", "ACCESSCORP": "Banking",
    "UBA": "Banking", "FIRSTHOLDCO": "Banking", "STANBIC": "Banking",
    "FIDELITYBK": "Banking", "FCMB": "Banking", "ETI": "Banking",
    "JAIZBANK": "Banking", "FBNH": "Banking",
    "SEPLAT": "Oil & Gas", "TOTAL": "Oil & Gas", "OANDO": "Oil & Gas", "ARADEL": "Oil & Gas",
    "OKOMUOIL": "Agriculture", "PRESCO": "Agriculture",
    "TRANSCORP": "Conglomerates",
    "JBERGER": "Construction", "JULIUS": "Construction",
    "TRANSCOHOT": "Services", "NGXGROUP": "Services",
    "CUSTODIAN": "Insurance", "NEM": "Insurance", "MANSARD": "Insurance",
    "GEREGU": "Power & Utilities",
}


# ── TradingView screener ────────────────────────────────────────────────────────

async def fetch_tradingview_stocks() -> list[dict]:
    """Fetch all NGX stocks from TradingView screener API (returns ~200 stocks)."""
    payload = {
        "columns": TV_COLUMNS,
        "filter": [],
        "options": {"lang": "en"},
        "range": [0, 300],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
    }
    try:
        async with httpx.AsyncClient(timeout=30, headers=TV_HEADERS) as client:
            response = await client.post(TV_SCREENER_URL, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        logger.error(f"TradingView screener error: {e}")
        return []

    stocks: list[dict] = []
    for item in data.get("data", []):
        raw_sym = item.get("s", "")     # "NGX:DANGCEM"
        d = item.get("d", [])
        if not raw_sym or len(d) < len(TV_COLUMNS):
            continue
        symbol = raw_sym.split(":")[-1].upper()
        try:
            price = d[2]
            if price is None or price <= 0:
                continue
            stocks.append({
                "symbol": symbol,
                "name": d[1] or d[0] or symbol,
                "sector": SECTOR_MAP.get(symbol),
                "price": float(price),
                "prev_close": None,
                "change_abs": d[4],
                "change_pct": d[3] or 0.0,
                "volume": float(d[5] or 0),
                "market_cap": d[6],
                "eps": d[7],
                "pe_ratio": d[8],
                "dividend_yield": d[9],
                "high_52w": d[10],
                "low_52w": d[11],
                "updated_at": datetime.now(timezone.utc),
            })
        except (IndexError, TypeError, ValueError):
            continue

    logger.info(f"TradingView screener: {len(stocks)} NGX stocks fetched")
    return stocks


# ── NGX official scraper ───────────────────────────────────────────────────────

async def scrape_ngx() -> list[dict]:
    """Fetch and parse the NGX equities price list (official close prices)."""
    try:
        async with httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True) as client:
            response = await client.get(NGX_URL)
            response.raise_for_status()
    except Exception as e:
        logger.error(f"NGX scrape HTTP error: {e}")
        return []
    return _parse_ngx_html(response.text)


def _parse_ngx_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    stocks = []
    table = soup.find("table")
    if not table:
        logger.warning("No table found in NGX HTML — site structure may have changed")
        return []

    rows = table.find_all("tr")[1:]
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        try:
            symbol = cells[0].get_text(strip=True).upper()
            name = cells[1].get_text(strip=True)
            price_text = cells[2].get_text(strip=True).replace(",", "")
            prev_close_text = cells[3].get_text(strip=True).replace(",", "")
            change_text = cells[4].get_text(strip=True).replace(",", "")
            change_pct_text = cells[5].get_text(strip=True).replace("%", "").replace(",", "")

            price = float(price_text) if price_text else 0.0
            prev_close = float(prev_close_text) if prev_close_text else price
            change = float(change_text) if change_text else 0.0
            change_pct = float(change_pct_text) if change_pct_text else 0.0

            volume = 0.0
            if len(cells) > 7:
                vol_text = cells[6].get_text(strip=True).replace(",", "")
                try:
                    volume = float(vol_text)
                except ValueError:
                    pass

            stocks.append({
                "symbol": symbol,
                "name": name,
                "sector": SECTOR_MAP.get(symbol),
                "price": price,
                "prev_close": prev_close,
                "change_abs": change,
                "change_pct": change_pct,
                "volume": volume,
                "updated_at": datetime.now(timezone.utc),
            })
        except (ValueError, IndexError):
            continue

    logger.info(f"NGX official scraper: {len(stocks)} stocks parsed")
    return stocks


# ── Merge & persist ────────────────────────────────────────────────────────────

async def upsert_stocks(stocks: list[dict]) -> None:
    """Upsert scraped stocks into the stock_cache table."""
    if not stocks:
        return

    async with AsyncSessionLocal() as db:
        for s in stocks:
            values = {
                "symbol": s["symbol"],
                "name": s["name"],
                "sector": s.get("sector"),
                "price": s.get("price", 0.0),
                "prev_close": s.get("prev_close"),
                "change": s.get("change_abs", 0.0),
                "change_pct": s.get("change_pct", 0.0),
                "volume": s.get("volume", 0.0),
                "market_cap": s.get("market_cap"),
                "pe_ratio": s.get("pe_ratio"),
                "eps": s.get("eps"),
                "dividend_yield": s.get("dividend_yield"),
                "high_52w": s.get("high_52w"),
                "low_52w": s.get("low_52w"),
                "updated_at": s.get("updated_at", datetime.now(timezone.utc)),
            }
            stmt = (
                pg_insert(StockCache)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["symbol"],
                    set_={k: v for k, v in values.items() if k != "symbol"},
                )
            )
            await db.execute(stmt)
        await db.commit()

    logger.info(f"Upserted {len(stocks)} stocks into cache")


async def run_scraper_once() -> int:
    """
    Primary: TradingView screener (rich data — PE, EPS, market cap, 52w H/L).
    Secondary: NGX official site (official close confirmation).
    Merges both, writes to stock_cache. Returns count of stocks persisted.
    """
    # Run both fetches concurrently
    tv_stocks, ngx_stocks = await asyncio.gather(
        fetch_tradingview_stocks(),
        scrape_ngx(),
        return_exceptions=True,
    )

    if isinstance(tv_stocks, Exception):
        logger.error(f"TradingView fetch failed: {tv_stocks}")
        tv_stocks = []
    if isinstance(ngx_stocks, Exception):
        logger.error(f"NGX fetch failed: {ngx_stocks}")
        ngx_stocks = []

    # Build merged dict: TV as base, NGX official price overrides where available
    merged: dict[str, dict] = {s["symbol"]: s for s in tv_stocks}

    for s in ngx_stocks:
        sym = s["symbol"]
        if sym in merged:
            # Trust NGX Group for price, prev_close, change; keep TV for PE/EPS/52w etc.
            merged[sym]["price"] = s["price"]
            merged[sym]["prev_close"] = s.get("prev_close")
            merged[sym]["change_abs"] = s.get("change_abs", merged[sym].get("change_abs", 0))
            merged[sym]["change_pct"] = s.get("change_pct", merged[sym].get("change_pct", 0))
            if s.get("volume"):
                merged[sym]["volume"] = s["volume"]
        else:
            merged[sym] = s

    stocks = list(merged.values())
    if stocks:
        await upsert_stocks(stocks)

    logger.info(f"Scraper run complete: {len(stocks)} stocks (TV={len(tv_stocks)}, NGX={len(ngx_stocks)})")
    return len(stocks)


# ── Query helpers ──────────────────────────────────────────────────────────────

async def get_cached_stocks(db: AsyncSession) -> list[StockCache]:
    result = await db.execute(select(StockCache).order_by(StockCache.symbol))
    return result.scalars().all()


async def get_cached_stock(db: AsyncSession, symbol: str) -> Optional[StockCache]:
    result = await db.execute(
        select(StockCache).where(StockCache.symbol == symbol.upper())
    )
    return result.scalar_one_or_none()
