"""Live-streaming companion to /api/market/options/chain.

The REST endpoint is a one-shot snapshot. This route loads the same chain
the same way (TastytradeOptionChainProvider.get_option_chain — one code
path, one shape), then keeps a DXLink session open per connected client and
pushes bid/ask updates as they arrive.

Protocol (JSON messages over the WebSocket):
  Client -> server: {"action": "subscribe", "symbol": "...", "expirationDate": "YYYY-MM-DD",
                     "dte": 30, "strike_count": 20}     # expirationDate, else nearest dte
                     {"action": "unsubscribe"}
  Server -> client: {"type": "snapshot", "chain": {...}}   # same shape as the REST endpoint
                     {"type": "quote", "symbol": "...", "bid": 1.23, "ask": 1.45}
                     {"type": "underlying_quote", "price": 123.45}
                     {"type": "error", "message": "..."}

Auth: the token (a query param — a WebSocket handshake can't carry an
Authorization header) is checked on connect, and the user is re-checked
every USER_RECHECK_SECONDS while open, so disabling an account or resetting
its password closes the stream (4401). Idle sign-out closes it from the page.
"""

import asyncio
import logging
import time
from collections import Counter
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from api.auth import token_user
from api.market.params import Symbol
from broker.tastytrade import DXLinkStreamer, get_shared_client
from broker.tastytrade.client import _finite_float
from service.market.chain_providers import TastytradeOptionChainProvider
from service.market.errors import UNAVAILABLE_MESSAGE, MarketDataError, SymbolNotFound

logger = logging.getLogger(__name__)
router = APIRouter()

USER_RECHECK_SECONDS = 60
MAX_STREAMS_PER_USER = 3
MAX_STRIKE_COUNT = 100
_open_streams: Counter = Counter()  # user id -> open sockets (one process)


class Subscribe(BaseModel):
    symbol: Symbol
    expirationDate: Optional[date] = None
    dte: Optional[int] = Field(None, ge=0, le=1000)
    strike_count: int = Field(20, ge=1, le=MAX_STRIKE_COUNT)


def _mid(event: dict) -> Optional[float]:
    bid, ask = _finite_float(event.get("bidPrice")), _finite_float(event.get("askPrice"))
    return (bid + ask) / 2 if bid is not None and ask is not None else (bid if bid is not None else ask)


@router.websocket("/chain")
async def stream_chain(websocket: WebSocket, token: str = Query(...)):
    user = token_user(token)
    if user is None:
        await websocket.close(code=4401)
        return
    if _open_streams[user.id] >= MAX_STREAMS_PER_USER:
        await websocket.close(code=4429)
        return
    await websocket.accept()
    _open_streams[user.id] += 1

    provider = TastytradeOptionChainProvider()
    streamer: Optional[DXLinkStreamer] = None
    listen_task: Optional[asyncio.Task] = None

    async def send_error(message: str):
        await websocket.send_json({"type": "error", "message": message})

    async def stop_streaming():
        nonlocal streamer, listen_task
        if listen_task is not None:
            listen_task.cancel()
            try:
                await listen_task
            except asyncio.CancelledError:
                pass
            listen_task = None
        if streamer is not None:
            await streamer.__aexit__(None, None, None)
            streamer = None

    async def forward_quotes(valid_symbols: set, underlying_symbol: Optional[str]):
        # Runs for one subscription; cancelled by stop_streaming(). The
        # underlying's own quotes share the channel, so spot stays live too.
        try:
            async for event in streamer.listen("Quote"):
                symbol = event.get("eventSymbol")
                if symbol == underlying_symbol:
                    price = _mid(event)
                    if price is not None:
                        await websocket.send_json({"type": "underlying_quote", "price": price})
                elif symbol in valid_symbols:
                    # dxFeed marks "no value" with "NaN" — sanitized to null.
                    await websocket.send_json({
                        "type": "quote",
                        "symbol": symbol,
                        "bid": _finite_float(event.get("bidPrice")),
                        "ask": _finite_float(event.get("askPrice")),
                    })
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Chain stream forwarding error: %s", e)
            try:
                await send_error("Live quote stream dropped")
            except Exception:
                pass

    async def subscribe(req: Subscribe):
        nonlocal streamer, listen_task
        await stop_streaming()
        if req.expirationDate is None and req.dte is None:
            await send_error("Pick an expiration")
            return
        expiration = req.expirationDate.isoformat() if req.expirationDate else None

        t0 = time.monotonic()
        try:
            # The provider's blocking calls each run their own event loop, so
            # they go to a worker thread rather than this one.
            chain = await asyncio.to_thread(provider.get_option_chain, req.symbol, req.dte, req.strike_count, expiration)
        except SymbolNotFound:
            await send_error(f"No option chain found for {req.symbol}")
            return
        except MarketDataError:
            await send_error(UNAVAILABLE_MESSAGE)
            return
        logger.info("Chain load for %s: %d strikes in %.0fms", req.symbol, len(chain["chain"]) if chain else 0,
                    (time.monotonic() - t0) * 1000)
        if chain is None:
            await send_error(f"No option chain found for {req.symbol}" + (f" on {expiration}" if expiration else ""))
            return
        await websocket.send_json({"type": "snapshot", "chain": chain})

        # A contract's "symbol" in the chain IS its dxFeed streamer symbol,
        # so quote events forward under the same key with no translation.
        valid_symbols = {
            leg["symbol"] for row in chain["chain"] for leg in (row["call"], row["put"]) if leg and leg.get("symbol")
        }
        try:
            client = get_shared_client()
            # Best-effort: keeps the underlying's price live; without it the
            # chain still works with spot frozen at the snapshot.
            try:
                underlying_symbol = await asyncio.to_thread(client.resolve_underlying_streamer_symbol, req.symbol)
            except Exception as e:
                logger.error("Failed to resolve underlying streamer symbol for %s: %s", req.symbol, e)
                underlying_symbol = None
            quote_token = await asyncio.to_thread(client.get_quote_token)
            streamer = DXLinkStreamer(quote_token)
            await streamer.__aenter__()
            await streamer.subscribe("Quote", list(valid_symbols) + ([underlying_symbol] if underlying_symbol else []))
        except Exception as e:
            logger.error("Failed to open live quote stream for %s: %s", req.symbol, e)
            await send_error("Could not start live quote stream")
            streamer = None
            return
        listen_task = asyncio.create_task(forward_quotes(valid_symbols, underlying_symbol))

    try:
        next_check = time.monotonic() + USER_RECHECK_SECONDS
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=max(next_check - time.monotonic(), 0.1))
            except asyncio.TimeoutError:
                if token_user(token, check_expiry=False) is None:
                    await websocket.close(code=4401)
                    return
                next_check = time.monotonic() + USER_RECHECK_SECONDS
                continue
            action = msg.get("action") if isinstance(msg, dict) else None
            if action == "subscribe":
                try:
                    req = Subscribe.model_validate(msg)
                except ValidationError as e:
                    await send_error("Invalid subscribe request: " + "; ".join(
                        f"{err['loc'][-1] if err['loc'] else 'input'}: {err['msg']}" for err in e.errors()))
                    continue
                await subscribe(req)
            elif action == "unsubscribe":
                await stop_streaming()
    except WebSocketDisconnect:
        pass
    finally:
        await stop_streaming()
        _open_streams[user.id] -= 1
        if _open_streams[user.id] <= 0:
            del _open_streams[user.id]
