"""
SMS service via Termii (Nigeria-focused SMS gateway).
Docs: https://developers.termii.com/
"""
import logging
from typing import Optional

import httpx
from app.config import settings

logger = logging.getLogger(__name__)


async def send_sms(phone: str, message: str) -> bool:
    """Send SMS via Termii. Phone should include country code e.g. +2348012345678."""
    if not settings.TERMII_API_KEY:
        logger.warning(f"Termii API key not configured — skipping SMS to {phone}")
        return False

    # Normalize phone: strip + if present, add 234 prefix
    phone_clean = phone.replace("+", "").replace(" ", "")
    if phone_clean.startswith("0"):
        phone_clean = "234" + phone_clean[1:]

    payload = {
        "to": phone_clean,
        "from": settings.TERMII_SENDER_ID,
        "sms": message,
        "type": "plain",
        "channel": "generic",
        "api_key": settings.TERMII_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{settings.TERMII_BASE_URL}/sms/send", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == "ok":
                logger.info(f"SMS sent to {phone_clean}")
                return True
            else:
                logger.warning(f"Termii returned non-ok: {data}")
                return False
    except Exception as e:
        logger.error(f"SMS error to {phone}: {e}")
        return False


async def send_otp(phone: str, otp: str) -> bool:
    msg = f"KB & Co: Your verification code is {otp}. Valid for 10 minutes. Do not share."
    return await send_sms(phone, msg)


async def send_price_alert_sms(phone: str, symbol: str, price: float, direction: str) -> bool:
    arrow = "rose above" if direction == "above" else "fell below"
    msg = f"KB & Co Alert: {symbol} has {arrow} your target price. Current: ₦{price:,.2f}. Log in to act."
    return await send_sms(phone, msg)


async def send_dividend_sms(phone: str, symbol: str, amount: float, ex_date: str) -> bool:
    msg = f"KB & Co: {symbol} declared ₦{amount:,.2f}/share dividend. Ex-date: {ex_date}. Check Dividend Center."
    return await send_sms(phone, msg)


async def send_kyc_sms(phone: str, status: str) -> bool:
    if status == "verified":
        msg = "KB & Co: Your KYC has been verified! Your trading account is now active. Log in to start trading."
    else:
        msg = f"KB & Co: Your KYC status is now '{status}'. Please log in and update your documents."
    return await send_sms(phone, msg)


async def send_payment_sms(phone: str, plan: str, amount: float) -> bool:
    msg = f"KB & Co: Payment of ₦{amount:,.0f} received. Your {plan.title()} plan is now active. Enjoy premium features!"
    return await send_sms(phone, msg)
