from sqlalchemy import Column, String, Float, DateTime, Enum, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum
from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class PlanEnum(str, enum.Enum):
    free = "free"
    premium = "premium"
    elite = "elite"


class SubStatusEnum(str, enum.Enum):
    active = "active"
    cancelled = "cancelled"
    expired = "expired"
    pending = "pending"


class PaymentStatusEnum(str, enum.Enum):
    pending = "pending"
    successful = "successful"
    failed = "failed"
    refunded = "refunded"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    plan = Column(Enum(PlanEnum), nullable=False)
    status = Column(Enum(SubStatusEnum), default=SubStatusEnum.pending)
    flw_subscription_id = Column(String, nullable=True)
    amount = Column(Float, nullable=False, default=0)
    billing_cycle = Column(String, default="monthly")
    started_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="subscriptions")
    payments = relationship("Payment", back_populates="subscription")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    subscription_id = Column(String, ForeignKey("subscriptions.id"), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="NGN")
    status = Column(Enum(PaymentStatusEnum), default=PaymentStatusEnum.pending)
    tx_ref = Column(String, unique=True, nullable=False)
    flw_tx_id = Column(String, nullable=True)
    payment_type = Column(String, nullable=True)
    narration = Column(Text, nullable=True)
    customer_email = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    verified_at = Column(DateTime(timezone=True), nullable=True)

    subscription = relationship("Subscription", back_populates="payments")
