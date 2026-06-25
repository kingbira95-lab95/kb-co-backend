from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    avatar: Optional[str]
    plan: str
    kyc_status: str
    is_admin: bool
    phone: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None


class KYCSubmit(BaseModel):
    bvn: Optional[str] = None
    nin: Optional[str] = None
    address: str
    city: str
    state: str
    bank_name: str
    account_number: str
    account_name: str
    id_type: str
    id_number: str


class KYCOut(BaseModel):
    status: str
    submitted_at: Optional[datetime]
    reviewed_at: Optional[datetime]
    rejection_reason: Optional[str]

    class Config:
        from_attributes = True
