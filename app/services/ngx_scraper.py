"""
NGX live price scraper.

Primary source  : TradingView Nigeria screener API (price, PE, EPS, market-cap, 52w H/L, div yield)
Secondary source: NGX Group equities price list (official closing prices)

Merges both sources — TradingView for richer metrics, NGX for official close confirmation.
Updates the stock_cache table every NGX_SCRAPE_INTERVAL_MINUTES minutes (default 1440 = 24 h).
"""
import asyncio
import logging
import re
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

# Official JSON API that feeds the NGX equities price-list table
NGX_API_URL = (
    "https://doclib.ngxgroup.com/REST/api/statistics/equities/"
    "?market=&sector=&orderby=&pageSize=300&pageNo=0"
)

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
    """
    Fetch official NGX prices. Primary: the doclib JSON API that feeds the
    equities-price-list page (structured, includes sector). Fallback: parse
    the HTML table on the page itself.
    """
    stocks = await _fetch_ngx_api()
    if stocks:
        return stocks

    logger.warning("NGX JSON API returned nothing — falling back to HTML parse")
    try:
        async with httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True) as client:
            response = await client.get(NGX_URL)
            response.raise_for_status()
    except Exception as e:
        logger.error(f"NGX scrape HTTP error: {e}")
        return []
    return _parse_ngx_html(response.text)


async def _fetch_ngx_api() -> list[dict]:
    """Official NGX equities API — returns ~146 stocks with sector data."""
    try:
        async with httpx.AsyncClient(timeout=30, headers={**HEADERS, "Accept": "application/json"}, follow_redirects=True) as client:
            response = await client.get(NGX_API_URL)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        logger.error(f"NGX API error: {e}")
        return []

    if not isinstance(data, list):
        logger.warning("NGX API returned unexpected shape — expected a list")
        return []

    stocks: list[dict] = []
    for row in data:
        try:
            symbol = (row.get("Symbol") or "").strip().upper()
            if not symbol:
                continue
            prev_close = row.get("PrevClosingPrice")
            close = row.get("ClosePrice")
            traded = close is not None and close > 0
            price = close if traded else prev_close
            if price is None or price <= 0:
                continue

            change = row.get("Change") or 0.0
            change_pct = row.get("PercChange")
            if change_pct is None:
                change_pct = (change / prev_close * 100) if (traded and prev_close) else 0.0

            sector_raw = (row.get("Sector") or "").strip()
            sector = sector_raw.title() if sector_raw else SECTOR_MAP.get(symbol)
            name = (row.get("Company2") or symbol).strip()

            stocks.append({
                "symbol": symbol,
                "name": name,
                "sector": sector,
                "price": float(price),
                "prev_close": float(prev_close) if prev_close else None,
                "change_abs": float(change),
                "change_pct": round(float(change_pct), 2),
                "volume": float(row.get("Volume") or 0),
                "traded_today": traded,
                "updated_at": datetime.now(timezone.utc),
            })
        except (TypeError, ValueError):
            continue

    logger.info(f"NGX official API: {len(stocks)} stocks fetched")
    return stocks


def _ngx_num(text: str) -> Optional[float]:
    """Parse an NGX table cell into a float. '--', '♦', arrows etc. -> None."""
    cleaned = re.sub(r"[^\d.\-]", "", text or "")
    if not cleaned or cleaned in ("-", ".", "-."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_ngx_html(html: str) -> list[dict]:
    """
    Parse the NGX equities price list table. Actual column layout:
    Company | Previous Closing Price | Opening Price | High | Low | Close |
    Change | Trades | Volume | Value | Trade Date
    Columns are located by header text so minor reordering doesn't break us.
    """
    soup = BeautifulSoup(html, "lxml")
    stocks = []
    table = soup.find("table")
    if not table:
        logger.warning("No table found in NGX HTML — site structure may have changed")
        return []

    headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

    def find_col(pred, default: int) -> int:
        for i, h in enumerate(headers):
            if pred(h):
                return i
        return default

    i_company = find_col(lambda h: "company" in h or "symbol" in h, 0)
    i_prev = find_col(lambda h: "previous" in h, 1)
    i_close = find_col(lambda h: h == "close" or (h.startswith("clos") and "previous" not in h), 5)
    i_change = find_col(lambda h: h.startswith("change"), 6)
    i_volume = find_col(lambda h: "volume" in h, 8)

    rows = table.find_all("tr")[1:]
    for row in rows:
        cells = row.find_all("td")
        if len(cells) <= max(i_company, i_prev, i_close):
            continue
        try:
            raw_symbol = cells[i_company].get_text(strip=True).upper()
            # Strip market-flag tags like "CAVERTON [MRF]" / "ALEX [BMF]"
            symbol = re.sub(r"\s*\[.*?\]\s*", "", raw_symbol).strip()
            if not symbol:
                continue

            prev_close = _ngx_num(cells[i_prev].get_text(strip=True))
            close = _ngx_num(cells[i_close].get_text(strip=True))
            change = _ngx_num(cells[i_change].get_text(strip=True)) if len(cells) > i_change else None
            volume = _ngx_num(cells[i_volume].get_text(strip=True)) if len(cells) > i_volume else None

            # Only rows with an actual traded Close carry a fresh price;
            # untraded rows ('--') would just echo yesterday's close.
            traded = close is not None and close > 0
            price = close if traded else prev_close
            if price is None or price <= 0:
                continue

            change_abs = change if change is not None else (close - prev_close if traded and prev_close else 0.0)
            change_pct = (change_abs / prev_close * 100) if prev_close else 0.0

            stocks.append({
                "symbol": symbol,
                "name": symbol.title(),
                "sector": SECTOR_MAP.get(symbol),
                "price": price,
                "prev_close": prev_close,
                "change_abs": change_abs,
                "change_pct": round(change_pct, 2),
                "volume": volume or 0.0,
                "traded_today": traded,
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
            merged[sym]["prev_close"] = s.get("prev_close") or merged[sym].get("prev_close")
            if not merged[sym].get("sector") and s.get("sector"):
                merged[sym]["sector"] = s["sector"]
            if s.get("traded_today"):
                # Trust NGX official traded price; keep TV for PE/EPS/52w etc.
                merged[sym]["price"] = s["price"]
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
