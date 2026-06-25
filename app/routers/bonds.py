"""
Bond / Fixed Income router.

GET  /bonds/offerings          — current NTB offerings (3 tenors)
GET  /bonds/history            — full auction history (paginated)
GET  /bonds/chart              — annual average rates for chart
GET  /bonds/trend/{tenor}      — quarterly rate trend for one tenor
POST /bonds/calculate          — preview purchase (discount, price, yield)
POST /bonds/purchase           — buy an NTB (requires verified KYC)
GET  /bonds/my-portfolio       — user's active bond holdings
GET  /bonds/my-portfolio/{id}  — single bond holding detail
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.bond import BondPurchase
from app.models.user import User, KYCStatusEnum
from app.core.deps import get_current_user
from app.services.bond_service import (
    get_current_offerings,
    get_history,
    get_chart_data,
    get_historical_rate_trend,
    calculate_ntb_purchase,
)
from app.services.email_service import send_email
from app.config import settings

router = APIRouter(prefix="/bonds", tags=["bonds"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class PurchaseCalculateRequest(BaseModel):
    face_value: float
    tenor: int        # 91 | 182 | 364
    stop_rate: float  # from current offering


class PurchaseRequest(BaseModel):
    instrument_id: str
    tenor: int
    stop_rate: float
    maturity_date: str
    auction_date: str
    face_value: float
    payment_ref: Optional[str] = None


class BondOut(BaseModel):
    id: str
    instrument_id: str
    security_type: str
    tenor: int
    stop_rate: float
    auction_date: str
    maturity_date: str
    face_value: float
    discount_amount: float
    purchase_price: float
    expected_return: float
    status: str
    purchased_at: datetime

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/offerings")
async def current_offerings():
    """Current NTB offerings derived from latest CBN auction data."""
    return get_current_offerings()


@router.get("/history")
async def auction_history(
    tenor: Optional[int] = None,
    from_year: int = 2020,
    limit: int = 100,
):
    """Historical CBN NTB auction data."""
    data = get_history()
    if tenor:
        data = [r for r in data if r['tenor'] == tenor]
    data = [r for r in data if int(r['auctionDate'][:4]) >= from_year]
    return data[:limit]


@router.get("/chart")
async def rate_chart():
    """Annual average NTB stop rates (2002–2026) — for the main rate history chart."""
    return get_chart_data()


@router.get("/trend/{tenor}")
async def rate_trend(tenor: int, from_year: int = 2015):
    """Quarterly average rate trend for a specific tenor."""
    if tenor not in (91, 182, 364):
        raise HTTPException(status_code=400, detail="tenor must be 91, 182, or 364")
    return get_historical_rate_trend(tenor, from_year)


@router.post("/calculate")
async def calculate_purchase(body: PurchaseCalculateRequest):
    """Preview the economics of an NTB purchase (no auth required)."""
    if body.tenor not in (91, 182, 364):
        raise HTTPException(status_code=400, detail="tenor must be 91, 182, or 364")
    if body.face_value < 50_000:
        raise HTTPException(status_code=400, detail="Minimum investment is ₦50,000")
    return calculate_ntb_purchase(body.face_value, body.tenor, body.stop_rate)


@router.post("/purchase", response_model=BondOut, status_code=201)
async def buy_bond(
    body: PurchaseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Purchase an NTB. Requires verified KYC trading account."""
    if user.kyc_status != KYCStatusEnum.verified:
        raise HTTPException(
            status_code=403,
            detail="KYC verification required before purchasing bonds. Complete your trading account setup."
        )
    if body.tenor not in (91, 182, 364):
        raise HTTPException(status_code=400, detail="Invalid tenor")
    if body.face_value < 50_000:
        raise HTTPException(status_code=400, detail="Minimum investment is ₦50,000")

    calc = calculate_ntb_purchase(body.face_value, body.tenor, body.stop_rate)

    bond = BondPurchase(
        id=str(uuid.uuid4()),
        user_id=user.id,
        instrument_id=body.instrument_id,
        security_type="NTB",
        tenor=body.tenor,
        stop_rate=body.stop_rate,
        auction_date=body.auction_date,
        maturity_date=body.maturity_date,
        face_value=calc['face_value'],
        discount_amount=calc['discount_amount'],
        purchase_price=calc['purchase_price'],
        expected_return=calc['expected_return'],
        status="active",
        payment_ref=body.payment_ref,
    )
    db.add(bond)
    await db.commit()
    await db.refresh(bond)

    # Confirmation email
    try:
        tenor_label = f"{body.tenor}-Day T-Bill"
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;background:#0d1526;padding:32px;border-radius:12px;border:1px solid rgba(212,175,55,.2)">
          <div style="color:#D4AF37;font-size:18px;font-weight:800;margin-bottom:8px">KB & Co</div>
          <h2 style="color:#fff;margin:0 0 16px">Bond Purchase Confirmed</h2>
          <p style="color:#9ca3af">Your NTB purchase has been recorded.</p>
          <table style="width:100%;border-collapse:collapse;margin:16px 0">
            <tr><td style="color:#6b7280;padding:6px 0">Instrument</td><td style="color:#fff;text-align:right;font-weight:600">{tenor_label}</td></tr>
            <tr><td style="color:#6b7280;padding:6px 0">Face Value</td><td style="color:#fff;text-align:right">&#8358;{calc['face_value']:,.2f}</td></tr>
            <tr><td style="color:#6b7280;padding:6px 0">You Pay</td><td style="color:#D4AF37;text-align:right;font-weight:700">&#8358;{calc['purchase_price']:,.2f}</td></tr>
            <tr><td style="color:#6b7280;padding:6px 0">Interest Earned</td><td style="color:#22c55e;text-align:right;font-weight:700">&#8358;{calc['discount_amount']:,.2f}</td></tr>
            <tr><td style="color:#6b7280;padding:6px 0">Stop Rate</td><td style="color:#fff;text-align:right">{body.stop_rate}% p.a.</td></tr>
            <tr><td style="color:#6b7280;padding:6px 0">Maturity Date</td><td style="color:#fff;text-align:right">{body.maturity_date}</td></tr>
          </table>
          <p style="color:#6b7280;font-size:11px">At maturity you will receive &#8358;{calc['expected_return']:,.2f}. Past performance does not guarantee future results.</p>
        </div>"""
        await send_email(user.email, f"NTB Purchase Confirmed — ₦{calc['face_value']:,.0f} {tenor_label}", html)
    except Exception:
        pass

    return bond


@router.get("/my-portfolio", response_model=list[BondOut])
async def my_bonds(
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BondPurchase).where(BondPurchase.user_id == user.id)
    if status:
        query = query.where(BondPurchase.status == status)
    query = query.order_by(BondPurchase.purchased_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/my-portfolio/{bond_id}", response_model=BondOut)
async def get_bond(
    bond_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BondPurchase).where(BondPurchase.id == bond_id, BondPurchase.user_id == user.id)
    )
    bond = result.scalar_one_or_none()
    if not bond:
        raise HTTPException(status_code=404, detail="Bond not found")
    return bond
