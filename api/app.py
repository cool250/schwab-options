from fastapi import FastAPI
from api.market import router as market_router
from api.position import router as position_router
from api.transactions import router as transactions_router
from api.agent import router as agent_router

app = FastAPI(
    title="Options Wheel API",
    version="1.0.0",
    description="REST API for the Options Wheel trading application.",
)

app.include_router(market_router, prefix="/market", tags=["Market"])
app.include_router(position_router, prefix="/positions", tags=["Positions"])
app.include_router(transactions_router, prefix="/transactions", tags=["Transactions"])
app.include_router(agent_router, prefix="/agent", tags=["Agent"])
