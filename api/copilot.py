import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from copilot.agent import chat

logger = logging.getLogger(__name__)
router = APIRouter()


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
    except Exception as e:
        logger.error("Copilot chat failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Copilot request failed: {e}")
