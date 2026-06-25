from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PaymentInitRequest(BaseModel):
    plan: str  # premium | elite
    billing_cycle: str = "monthly"


class PaymentInitResponse(BaseModel):
    payment_link: str
    tx_ref: str
    amount: float
    currency: str


class PaymentVerifyRequest(BaseModel):
    tx_ref: str
    transaction_id: str


class PaymentOut(BaseModel):
    id: str
    amount: float
    currency: str
    status: str
    tx_ref: str
    created_at: datetime
    verified_at: Optional[datetime]

    class Config:
        from_attributes = True


class SubscriptionOut(BaseModel):
    id: str
    plan: str
    status: str
    amount: float
    billing_cycle: str
    started_at: Optional[datetime]
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


PLAN_PRICES = {
    "premium": {"monthly": 2500, "annual": 25000},
    "elite": {"monthly": 5000, "annual": 50000},
}
