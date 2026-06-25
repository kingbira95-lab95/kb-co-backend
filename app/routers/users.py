from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.models.user import User, KYCDocument, KYCStatusEnum
from app.core.deps import get_current_user
from app.schemas.user import UserOut, UserUpdate, KYCSubmit, KYCOut
from app.services.email_service import send_kyc_update
from app.services.sms_service import send_kyc_sms

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/profile", response_model=UserOut)
async def get_profile(user: User = Depends(get_current_user)):
    return user


@router.put("/profile", response_model=UserOut)
async def update_profile(
    body: UserUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.name is not None:
        user.name = body.name
    if body.phone is not None:
        user.phone = body.phone
    if body.avatar is not None:
        user.avatar = body.avatar
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/kyc", response_model=KYCOut)
async def submit_kyc(
    body: KYCSubmit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check if KYC already verified
    if user.kyc_status == KYCStatusEnum.verified:
        raise HTTPException(status_code=400, detail="KYC already verified")

    result = await db.execute(select(KYCDocument).where(KYCDocument.user_id == user.id))
    kyc = result.scalar_one_or_none()

    if kyc:
        # Update existing
        kyc.bvn = body.bvn
        kyc.nin = body.nin
        kyc.address = body.address
        kyc.city = body.city
        kyc.state = body.state
        kyc.bank_name = body.bank_name
        kyc.account_number = body.account_number
        kyc.account_name = body.account_name
        kyc.id_type = body.id_type
        kyc.id_number = body.id_number
        kyc.status = KYCStatusEnum.submitted
        kyc.submitted_at = datetime.now(timezone.utc)
    else:
        kyc = KYCDocument(
            user_id=user.id,
            bvn=body.bvn,
            nin=body.nin,
            address=body.address,
            city=body.city,
            state=body.state,
            bank_name=body.bank_name,
            account_number=body.account_number,
            account_name=body.account_name,
            id_type=body.id_type,
            id_number=body.id_number,
            status=KYCStatusEnum.submitted,
        )
        db.add(kyc)

    user.kyc_status = KYCStatusEnum.submitted
    await db.commit()
    await db.refresh(kyc)
    return kyc


@router.get("/kyc", response_model=KYCOut)
async def get_kyc_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(KYCDocument).where(KYCDocument.user_id == user.id))
    kyc = result.scalar_one_or_none()
    if not kyc:
        raise HTTPException(status_code=404, detail="No KYC submission found")
    return kyc
