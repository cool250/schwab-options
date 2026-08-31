"""Live-streaming companion to /api/market/options/chain.

The REST endpoint (service/option_chain_providers.py) is a one-shot snapshot:
every load re-fetches quotes and closes the DXLink session. This route keeps
one DXLink session open per connected client and pushes bid/ask updates as
they arrive, using the same TastytradeClient/DXLinkStreamer building blocks —
DXLinkStreamer.listen() already supports this, it just wasn't used
continuously anywhere until now.

Protocol (JSON messages over the WebSocket):
  Client -> server: {"action": "subscribe", "symbol": "...", "dte": 30, "strike_count": 20}
                     {"action": "unsubscribe"}
  Server -> client: {"type": "snapshot", "chain": {...}}   # same shape as the REST endpoint
                     {"type": "quote", "symbol": "...", "bid": 1.23, "ask": 1.45}
                     {"type": "error", "message": "..."}
"""

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.auth import verify_token
from broker.tastytrade import DXLinkStreamer, TastytradeAPIError, TastytradeClient
from service.option_chain_providers import TastytradeOptionChainProvider

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/chain")
async def stream_chain(websocket: WebSocket, token: str = Query(...)):
    if not verify_token(token):
        await websocket.close(code=4401)
        return

    await websocket.accept()

    try:
        client = TastytradeClient.from_config()
    except ValueError as e:
        await websocket.send_json({"type": "error", "message": f"Tastytrade credentials unavailable: {e}"})
        await websocket.close(code=4500)
        return

    provider = TastytradeOptionChainProvider(client)

    streamer: DXLinkStreamer | None = None
    listen_task: asyncio.Task | None = None

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

    async def forward_quotes(valid_symbols: set):
        # Runs for the lifetime of one subscription — cancelled by
        # stop_streaming() when the client unsubscribes, resubscribes to
        # something else, or disconnects.
        try:
            async for event in streamer.listen("Quote"):
                symbol = event.get("eventSymbol")
                if symbol not in valid_symbols:
                    continue
                await websocket.send_json({
                    "type": "quote",
                    "symbol": symbol,
                    "bid": event.get("bidPrice"),
                    "ask": event.get("askPrice"),
                })
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Chain stream forwarding error: %s", e)
            try:
                await websocket.send_json({"type": "error", "message": "Live quote stream dropped"})
            except Exception:
                pass

    async def subscribe(symbol: str, dte: int, strike_count: int):
        nonlocal streamer, listen_task
        await stop_streaming()

        # get_live_underlying_price/get_chain_quotes/get_chain_greeks each wrap
        # their own asyncio.run(...) internally — fine for a callable running
        # in Starlette's sync-route thread pool (the REST snapshot path), but
        # calling them directly here would raise "asyncio.run() cannot be
        # called from a running event loop" since this handler is itself a
        # coroutine. Push each onto a worker thread instead.
        try:
            spot = await asyncio.to_thread(client.get_live_underlying_price, symbol)
            # Tastytrade's num_strikes keeps the N strikes closest to the
            # underlying total (not per side) — same doubling convention as
            # the REST snapshot path in TastytradeOptionChainProvider.
            contracts = client.get_options_chain(
                symbol,
                dte=dte,
                option_type="all",
                num_strikes=strike_count * 2,
                underlying_price=spot,
                fetch_live_price=False,
            )
        except (TastytradeAPIError, ValueError, TimeoutError) as e:
            await websocket.send_json({"type": "error", "message": f"Failed to fetch chain for {symbol}: {e}"})
            return

        if not contracts:
            await websocket.send_json({"type": "error", "message": f"No option chain found for {symbol}"})
            return

        try:
            quotes = await asyncio.to_thread(client.get_chain_quotes, contracts)
        except TastytradeAPIError as e:
            logger.error("Failed to fetch initial chain quotes for %s: %s", symbol, e)
            quotes = {}
        try:
            greeks = await asyncio.to_thread(client.get_chain_greeks, contracts)
        except TastytradeAPIError as e:
            logger.error("Failed to fetch initial chain greeks for %s: %s", symbol, e)
            greeks = {}

        snapshot = provider._normalize_chain(contracts, quotes, greeks, spot)
        if snapshot is None:
            await websocket.send_json({"type": "error", "message": f"No option chain found for {symbol}"})
            return
        await websocket.send_json({"type": "snapshot", "chain": snapshot})

        # A leg's normalized "symbol" field IS its dxFeed streamer-symbol (see
        # TastytradeOptionChainProvider._normalize_chain), so Quote events can
        # be forwarded to the frontend under that same key with no translation.
        valid_symbols = {c["streamer-symbol"] for c in contracts if c.get("streamer-symbol")}
        if not valid_symbols:
            return

        try:
            quote_token = client.get_quote_token()
            streamer = DXLinkStreamer(quote_token)
            await streamer.__aenter__()
            await streamer.subscribe("Quote", list(valid_symbols))
        except Exception as e:
            logger.error("Failed to open live quote stream for %s: %s", symbol, e)
            await websocket.send_json({"type": "error", "message": "Could not start live quote stream"})
            streamer = None
            return

        listen_task = asyncio.create_task(forward_quotes(valid_symbols))

    try:
        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")
            if action == "subscribe":
                try:
                    await subscribe(
                        msg["symbol"],
                        int(msg["dte"]),
                        int(msg.get("strike_count", 20)),
                    )
                except (KeyError, TypeError, ValueError) as e:
                    await websocket.send_json({"type": "error", "message": f"Invalid subscribe request: {e}"})
            elif action == "unsubscribe":
                await stop_streaming()
    except WebSocketDisconnect:
        pass
    finally:
        await stop_streaming()
