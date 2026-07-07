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

BASE_SYSTEM_PROMPT = """You are KB & Co Corporate Investment Limited's AI Investment Advisor. \
You are an expert on Nigerian Exchange (NGX) stocks, wealth management, and investment strategy.

Always provide specific, actionable Nigerian market insights. When asked about a stock price, \
use ONLY the live prices provided in the LIVE MARKET DATA section below — never use outdated \
hardcoded prices. Include NGX stock symbols, current prices, and percentage changes when relevant. \
Format responses in clear markdown with bullet points and headers.

Legal disclaimer to always include at the end: "This is educational content only. Past performance \
does not guarantee future returns. Always consult a financial advisor.\""""


def build_system_prompt(prices: dict) -> str:
    if not prices:
        return BASE_SYSTEM_PROMPT
    lines = ["## LIVE MARKET DATA (use these prices — updated in real-time)\n"]
    # Sort by symbol for readability, cap at 119 entries
    for symbol, data in sorted(prices.items())[:120]:
        price = data.get("price", 0)
        change = data.get("change", 0)
        change_pct = data.get("changePct", 0)
        direction = "▲" if change >= 0 else "▼"
        lines.append(f"- {symbol}: ₦{price:.2f} {direction}{abs(change_pct):.2f}%")
    market_data = "\n".join(lines)
    return f"{BASE_SYSTEM_PROMPT}\n\n{market_data}"


class ChatMessage(BaseModel):
    role: str
    content: str


class PriceData(BaseModel):
    price: float
    change: float
    changePct: float


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    prices: dict[str, PriceData] = {}


class ChatResponse(BaseModel):
    content: str


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not settings.OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI service not configured. Set OPENROUTER_API_KEY in backend environment variables.",
        )

    prices_dict = {sym: p.model_dump() for sym, p in req.prices.items()}
    system_prompt = build_system_prompt(prices_dict)

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            *[{"role": m.role, "content": m.content} for m in req.messages[-10:]],
        ],
        "max_tokens": 700,
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