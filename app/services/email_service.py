"""Async email service via SMTP (works with Gmail, Zoho, custom SMTP)."""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib
from app.config import settings

logger = logging.getLogger(__name__)

GOLD = "#D4AF37"
NAVY = "#0A0F1E"


def _base_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  body {{ margin:0; padding:0; background:{NAVY}; font-family:Inter,Arial,sans-serif; }}
  .wrap {{ max-width:560px; margin:0 auto; background:#0d1526; border:1px solid rgba(212,175,55,.2); border-radius:12px; overflow:hidden; }}
  .hdr {{ background:linear-gradient(135deg,#0d1526,#1a2540); padding:32px 32px 24px; border-bottom:1px solid rgba(212,175,55,.15); }}
  .logo {{ color:{GOLD}; font-size:18px; font-weight:800; letter-spacing:.5px; }}
  .sub {{ color:#6b7280; font-size:11px; margin-top:2px; }}
  .body {{ padding:28px 32px; color:#d1d5db; font-size:14px; line-height:1.6; }}
  .body h2 {{ color:#fff; font-size:20px; margin:0 0 12px; }}
  .btn {{ display:inline-block; margin:20px 0; padding:12px 28px; background:linear-gradient(135deg,{GOLD},{GOLD}cc);
           color:#000; font-weight:700; font-size:14px; border-radius:8px; text-decoration:none; }}
  .ftr {{ padding:16px 32px; background:#080d18; color:#4b5563; font-size:11px; text-align:center; }}
</style></head>
<body><div class="wrap">
  <div class="hdr"><div class="logo">KB & Co</div><div class="sub">Corporate Investment Limited · Investing In The Future.</div></div>
  <div class="body"><h2>{title}</h2>{body}</div>
  <div class="ftr">© 2026 KB & Co Corporate Investment Limited. Investment intelligence platform.<br>
  This is an automated notification. Do not reply to this email.</div>
</div></body></html>"""


async def send_email(to: str, subject: str, html: str, text: str = "") -> bool:
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning(f"SMTP not configured — skipping email to {to}: {subject}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        msg["To"] = to
        if text:
            msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email error to {to}: {e}")
        return False


async def send_welcome(to: str, name: str) -> bool:
    html = _base_html(
        f"Welcome to KB & Co, {name}!",
        f"""<p>Your account has been created. You now have access to Nigeria's premier investment intelligence platform.</p>
        <p>✅ Real-time NGX stock data<br>✅ AI-powered analysis<br>✅ Portfolio tracking<br>✅ Dividend alerts</p>
        <a class="btn" href="{settings.FRONTEND_URL}">Open Dashboard</a>
        <p>Upgrade to <strong style="color:{GOLD}">Premium</strong> or <strong style="color:{GOLD}">Elite</strong> to unlock trading, AI advisor, and PDF reports.</p>"""
    )
    return await send_email(to, "Welcome to KB & Co Corporate Investment", html)


async def send_price_alert(to: str, name: str, symbol: str, price: float, target: float, direction: str) -> bool:
    arrow = "▲" if direction == "above" else "▼"
    color = "#22c55e" if direction == "above" else "#ef4444"
    html = _base_html(
        f"Price Alert: {symbol} {arrow} ₦{price:,.2f}",
        f"""<p>Hi {name},</p>
        <p>Your price alert for <strong style="color:{GOLD}">{symbol}</strong> has been triggered.</p>
        <table style="width:100%;background:#0a0f1e;border-radius:8px;padding:16px;margin:16px 0">
          <tr><td style="color:#6b7280">Current Price</td><td style="color:{color};font-weight:700;text-align:right">₦{price:,.2f}</td></tr>
          <tr><td style="color:#6b7280">Your Target</td><td style="color:#fff;text-align:right">₦{target:,.2f} ({direction})</td></tr>
        </table>
        <a class="btn" href="{settings.FRONTEND_URL}">View Stock</a>"""
    )
    return await send_email(to, f"KB & Co Alert: {symbol} {arrow} ₦{price:,.2f}", html)


async def send_dividend_notification(to: str, name: str, symbol: str, amount: float, ex_date: str) -> bool:
    html = _base_html(
        f"Dividend Alert: {symbol}",
        f"""<p>Hi {name},</p>
        <p><strong style="color:{GOLD}">{symbol}</strong> has declared a dividend.</p>
        <table style="width:100%;background:#0a0f1e;border-radius:8px;padding:16px;margin:16px 0">
          <tr><td style="color:#6b7280">Dividend Per Share</td><td style="color:#22c55e;font-weight:700;text-align:right">₦{amount:,.2f}</td></tr>
          <tr><td style="color:#6b7280">Ex-Dividend Date</td><td style="color:#fff;text-align:right">{ex_date}</td></tr>
        </table>
        <p>Ensure you hold shares before the ex-date to qualify for this dividend.</p>
        <a class="btn" href="{settings.FRONTEND_URL}">View Dividend Center</a>"""
    )
    return await send_email(to, f"KB & Co: {symbol} Dividend Declared — ₦{amount:,.2f}/share", html)


async def send_subscription_confirmation(to: str, name: str, plan: str, expires: str) -> bool:
    html = _base_html(
        f"Subscription Activated: {plan.title()} Plan",
        f"""<p>Hi {name},</p>
        <p>Your <strong style="color:{GOLD}">{plan.title()} Plan</strong> subscription is now active.</p>
        <table style="width:100%;background:#0a0f1e;border-radius:8px;padding:16px;margin:16px 0">
          <tr><td style="color:#6b7280">Plan</td><td style="color:{GOLD};font-weight:700;text-align:right">{plan.title()}</td></tr>
          <tr><td style="color:#6b7280">Valid Until</td><td style="color:#fff;text-align:right">{expires}</td></tr>
        </table>
        <a class="btn" href="{settings.FRONTEND_URL}">Open Platform</a>"""
    )
    return await send_email(to, f"KB & Co: {plan.title()} Plan Activated", html)


async def send_kyc_update(to: str, name: str, status: str, reason: Optional[str] = None) -> bool:
    is_ok = status == "verified"
    color = "#22c55e" if is_ok else "#ef4444"
    extra = f"<p><strong>Reason:</strong> {reason}</p>" if reason else ""
    html = _base_html(
        f"KYC {'Verified' if is_ok else 'Update Required'}",
        f"""<p>Hi {name},</p>
        <p>Your KYC verification status has been updated to: <strong style="color:{color}">{status.upper()}</strong></p>
        {extra}
        {'<p>You can now access your trading account and execute trades on the NGX.</p>' if is_ok else '<p>Please log in to update your documents.</p>'}
        <a class="btn" href="{settings.FRONTEND_URL}/trading">{'Open Trading Account' if is_ok else 'Update KYC'}</a>"""
    )
    return await send_email(to, f"KB & Co: KYC {status.title()}", html)
