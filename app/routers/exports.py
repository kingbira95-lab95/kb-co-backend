"""PDF and Excel export endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.portfolio import Portfolio
from app.models.stock import StockCache
from app.models.user import User
from app.core.deps import get_current_user
from app.services.pdf_export import generate_portfolio_pdf
from app.services.excel_export import generate_portfolio_excel, generate_stocks_excel

router = APIRouter(prefix="/exports", tags=["exports"])


def _get_prices(stocks: list) -> dict:
    return {s.symbol: s.price for s in stocks}


@router.get("/portfolio/{portfolio_id}/pdf")
async def export_portfolio_pdf(
    portfolio_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user.id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    stocks_result = await db.execute(select(StockCache))
    prices = _get_prices(stocks_result.scalars().all())

    holdings = [
        {"symbol": h.symbol, "shares": h.shares, "buy_price": h.buy_price, "buy_date": h.buy_date}
        for h in portfolio.holdings
    ]

    pdf_bytes = generate_portfolio_pdf(
        portfolio_name=portfolio.name,
        owner_name=user.name,
        holdings=holdings,
        prices=prices,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="KB-Co-{portfolio.name}-Report.pdf"'},
    )


@router.get("/portfolio/{portfolio_id}/excel")
async def export_portfolio_excel(
    portfolio_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user.id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    stocks_result = await db.execute(select(StockCache))
    prices = _get_prices(stocks_result.scalars().all())

    holdings = [
        {"symbol": h.symbol, "shares": h.shares, "buy_price": h.buy_price, "buy_date": h.buy_date}
        for h in portfolio.holdings
    ]

    xlsx_bytes = generate_portfolio_excel(
        portfolio_name=portfolio.name,
        owner_name=user.name,
        holdings=holdings,
        prices=prices,
    )

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="KB-Co-{portfolio.name}.xlsx"'},
    )


@router.get("/stocks/excel")
async def export_stocks_excel(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(StockCache).order_by(StockCache.symbol))
    stocks = result.scalars().all()

    stocks_dicts = [
        {
            "symbol": s.symbol, "name": s.name, "sector": s.sector,
            "price": s.price, "change": s.change, "change_pct": s.change_pct,
            "volume": s.volume, "market_cap": s.market_cap,
            "high_52w": s.high_52w, "low_52w": s.low_52w,
            "dividend_yield": s.dividend_yield,
        }
        for s in stocks
    ]

    xlsx_bytes = generate_stocks_excel(stocks_dicts)

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="KB-Co-NGX-Stocks.xlsx"'},
    )
