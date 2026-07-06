"""
AI chat proxy — forwards messages to OpenRouter so the API key never
touches the browser bundle.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

from app.config import settings

router = APIRouter(prefix="/ai", tags=["ai"])

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT = """You are KB & Co Corporate Investment Limited's AI Investment Advisor. \
You are an expert on Nigerian Exchange (NGX) stocks, wealth management, and investment strategy.

Key NGX stocks you know: DANGCEM (₦545), BUAFOODS (₦939), MTNN (₦265), ZENITHBANK (₦52.50), \
GTCO (₦58), ACCESSCORP (₦25.80), UBA (₦32.50), AIRTELAFRI (₦2150), SEPLAT (₦3880), \
BUACEMENT (₦118), FBNH (₦28.40), STANBIC (₦68), NESTLE (₦1020), OKOMUOIL (₦498), PRESCO (₦538).

Always provide specific, actionable Nigerian market insights. Include NGX stock symbols, \
current prices, and dividend yields when relevant. Format responses in clear markdown with \
bullet points and headers.

Legal disclaimer to always include: "This is educational content only. Past performance does \
not guarantee future returns. Always consult a financial advisor.\""""


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    content: str


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not settings.OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI service not configured. Set OPENROUTER_API_KEY in backend environment variables.",
        )

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *[{"role": m.role, "content": m.content} for m in req.messages[-10:]],
        ],
        "max_tokens": 600,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                OPENROUTER_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": settings.FRONTEND_URL,
                    "X-Title": "KB & Co Investment Platform",
                },
            )
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="AI service timed out. Please try again.")
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Could not reach AI service: {e}")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid OpenRouter API key.")
    if resp.status_code == 402:
        raise HTTPException(status_code=402, detail="OpenRouter account has insufficient credits.")
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="Rate limit reached. Please wait a moment.")
    if not resp.is_success:
        err = resp.json().get("error", {}).get("message", resp.text)
        raise HTTPException(status_code=502, detail=f"AI service error: {err}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return ChatResponse(content=content)