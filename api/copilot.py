import logging
from typing import Any, Optional

import openai
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from copilot.agent import chat

logger = logging.getLogger(__name__)
router = APIRouter()


# OpenAI failures are surfaced with their actual cause — otherwise the
# frontend only sees a bare 502, which reads like a broker outage when the
# real problem is e.g. an exhausted OpenAI credit balance.
def _openai_error_detail(e: openai.APIError) -> str:
    if isinstance(e, openai.APIConnectionError):
        return "Could not reach OpenAI. Check your network connection and try again."
    if isinstance(e, openai.AuthenticationError):
        return "OpenAI rejected the API key. Check OPENAI_API_KEY in .env."
    if isinstance(e, openai.RateLimitError):
        if e.code in ("insufficient_quota", "credit_balance_exhausted") or e.type == "insufficient_quota":
            return "OpenAI credits exhausted. Add credits at https://platform.openai.com/settings/organization/billing/."
        return "OpenAI rate limit reached. Please wait a moment and try again."
    if isinstance(e, openai.NotFoundError):
        return "OpenAI model not found. Check OPENAI_MODEL in .env."
    body = e.body if isinstance(e.body, dict) else {}
    return f"OpenAI error: {body.get('message') or e.message}"


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class PageContext(BaseModel):
    page: str
    data: dict[str, Any]


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    # What the user is currently looking at in the app (e.g. the StrikeLab
    # position being built) — folded into this turn's system prompt so the
    # agent can answer "explain this position" without the user restating
    # every strike. Optional: most pages don't set one.
    context: Optional[PageContext] = None


@router.post("/chat", summary="One turn of the read-only financial copilot agent")
def post_chat(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    try:
        return chat(
            [m.model_dump() for m in req.messages],
            page_context=req.context.model_dump() if req.context else None,
        )
    except openai.APIError as e:
        logger.error("Copilot chat failed (OpenAI): %s", e)
        raise HTTPException(status_code=502, detail=_openai_error_detail(e))
    except Exception as e:
        logger.error("Copilot chat failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Copilot request failed: {e}")
