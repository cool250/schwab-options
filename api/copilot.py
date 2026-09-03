import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from copilot.agent import chat

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@router.post("/chat", summary="One turn of the read-only financial copilot agent")
def post_chat(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    try:
        return chat([m.model_dump() for m in req.messages])
    except Exception as e:
        logger.error("Copilot chat failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Copilot request failed: {e}")
