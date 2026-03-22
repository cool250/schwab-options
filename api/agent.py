from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
from service.agent import AgentService

router = APIRouter()


class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


@router.post("/query", summary="Invoke the options-wheel AI agent")
def invoke_agent(request: QueryRequest):
    service = AgentService(session_id=request.session_id)
    result = service.invoke_llm(request.query)
    return {"response": result}
