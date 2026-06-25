from sqlalchemy import Column, String, Float, Integer, DateTime, Enum, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum
from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class BondStatusEnum(str, enum.Enum):
    active = "active"
    matured = "matured"
    cancelled = "cancelled"


class BondPurchase(Base):
    """A user's NTB / fixed-income purchase through the trading account."""
    __tablename__ = "bond_purchases"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)

    # Instrument details (from NTB auction data)
    instrument_id = Column(String, nullable=False)        # e.g. "NTB-91-2026-06-17"
    security_type = Column(String, nullable=False, default="NTB")
    tenor = Column(Integer, nullable=False)                # 91 | 182 | 364 days
    stop_rate = Column(Float, nullable=False)              # annualised yield %
    auction_date = Column(String, nullable=False)
    maturity_date = Column(String, nullable=False)

    # Investment amounts
    face_value = Column(Float, nullable=False)             # amount user invests (₦)
    discount_amount = Column(Float, nullable=False)        # interest earned upfront
    purchase_price = Column(Float, nullable=False)         # face_value − discount
    expected_return = Column(Float, nullable=False)        # face_value at maturity

    # Status
    status = Column(String, default=BondStatusEnum.active)
    purchased_at = Column(DateTime(timezone=True), server_default=func.now())
    matured_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    # Payment reference
    payment_ref = Column(String, nullable=True)

    user = relationship("User", backref="bond_purchases")
