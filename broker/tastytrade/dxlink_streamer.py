"""
DXLink WebSocket streamer for Tastytrade real-time market data.

Tastytrade doesn't expose live quotes over plain REST — TastytradeClient.
get_quote() / get_future_option_quote() both 404 in production (see their
docstrings). Real-time data instead requires DXLink, dxFeed's streaming
protocol. Auth flow:

  1. TastytradeClient.get_quote_token() -> {"token": ..., "dxlink-url": ...}
  2. Open a WebSocket to dxlink-url and run the DXLink SETUP/AUTH handshake
     with that token
  3. Open one FEED channel per event type, subscribe to symbols, receive
     FEED_DATA frames

This module implements steps 2-3. It's async (unlike the REST clients in
this repo) because streaming is inherently connection/event-driven.

The wire format (message shapes, keepalive cadence, and — critically — the
exact field order dxFeed streams back for each event type in COMPACT
frames) was cross-checked against tastyware/tastytrade's streamer.py
rather than reconstructed from memory, since a wrong field order silently
mislabels every value instead of raising an error.

Usage:
    from broker.tastytrade import TastytradeClient, DXLinkStreamer

    client = TastytradeClient.from_config()
    quote_token = client.get_quote_token()

    # Symbols must be dxFeed streamer-symbol format, e.g.
    # './ESZ4 EW4U4 240920P4700' — this is the 'streamer-symbol' field on
    # items returned by client.get_future_option_chain().
    async with DXLinkStreamer(quote_token) as streamer:
        await streamer.subscribe("Quote", ["./ESZ4 EW4U4 240920P4700"])
        async for event in streamer.listen("Quote"):
            print(event)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Iterable, Optional

import websockets

DXLINK_VERSION = "0.1-DXF-JS/0.3.0"
KEEPALIVE_INTERVAL = 30.0  # seconds; DXLink expects its own KEEPALIVE frame,
                           # not a transport-level ws ping
HANDSHAKE_TIMEOUT = 10.0  # seconds

# dxFeed event field order, in the exact sequence COMPACT-format FEED_DATA
# frames pack values in. Order matters: it must match what we declare in
# FEED_SETUP's acceptEventFields, and dxFeed streams values positionally
# with no field names attached — get this wrong and every value silently
# lands under the wrong key instead of erroring.
EVENT_FIELDS: dict[str, list[str]] = {
    "Quote": [
        "eventSymbol", "eventTime", "sequence", "timeNanoPart", "bidTime",
        "bidExchangeCode", "askTime", "askExchangeCode", "bidPrice", "askPrice",
        "bidSize", "askSize",
    ],
    "Trade": [
        "eventSymbol", "eventTime", "time", "timeNanoPart", "sequence",
        "exchangeCode", "dayId", "tickDirection", "extendedTradingHours",
        "price", "change", "size", "dayVolume", "dayTurnover",
    ],
    "Greeks": [
        "eventSymbol", "eventTime", "eventFlags", "index", "time", "sequence",
        "price", "volatility", "delta", "gamma", "theta", "rho", "vega",
    ],
    "Summary": [
        "eventSymbol", "eventTime", "dayId", "dayClosePriceType", "prevDayId",
        "prevDayClosePriceType", "openInterest", "dayOpenPrice", "dayHighPrice",
        "dayLowPrice", "dayClosePrice", "prevDayClosePrice", "prevDayVolume",
    ],
}


class DXLinkError(Exception):
    """Raised on a fatal DXLink protocol error or an ERROR frame from the server."""


class DXLinkStreamer:
    """Async client for Tastytrade's DXLink WebSocket market-data feed.

    Must be used as an async context manager — the SETUP/AUTH handshake
    runs in __aenter__, and a background task sends periodic KEEPALIVE
    frames to keep the session alive for the duration of the `with` block.
    """

    def __init__(self, quote_token: dict, keepalive_interval: float = KEEPALIVE_INTERVAL):
        self._url = quote_token["dxlink-url"]
        self._token = quote_token["token"]
        self._keepalive_interval = keepalive_interval

        self._ws: Optional[Any] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._keepalive_task: Optional[asyncio.Task] = None

        self._authorized = asyncio.Event()
        self._channels: dict[str, int] = {}  # event type -> channel id
        self._channel_opened: dict[str, asyncio.Event] = {}
        self._next_channel = 1
        self._queues: dict[str, asyncio.Queue] = {}  # event type -> parsed-event queue

    async def __aenter__(self) -> "DXLinkStreamer":
        self._ws = await websockets.connect(self._url)
        self._reader_task = asyncio.create_task(self._reader())

        await self._send(
            {
                "type": "SETUP",
                "channel": 0,
                "keepaliveTimeout": 60,
                "acceptKeepaliveTimeout": 60,
                "version": DXLINK_VERSION,
            }
        )
        await asyncio.wait_for(self._authorized.wait(), timeout=HANDSHAKE_TIMEOUT)

        self._keepalive_task = asyncio.create_task(self._keepalive())
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        for task in (self._keepalive_task, self._reader_task):
            if task is not None:
                task.cancel()
        if self._ws is not None:
            await self._ws.close()

    async def _send(self, message: dict) -> None:
        await self._ws.send(json.dumps(message))

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(self._keepalive_interval)
            await self._send({"type": "KEEPALIVE", "channel": 0})

    async def _reader(self) -> None:
        async for raw in self._ws:
            message = json.loads(raw)
            msg_type = message.get("type")

            if msg_type == "FEED_DATA":
                self._handle_feed_data(message["channel"], message["data"])
            elif msg_type == "AUTH_STATE":
                if message["state"] == "UNAUTHORIZED":
                    await self._send({"type": "AUTH", "channel": 0, "token": self._token})
                elif message["state"] == "AUTHORIZED":
                    self._authorized.set()
            elif msg_type == "CHANNEL_OPENED":
                event_type = self._event_type_for_channel(message["channel"])
                self._channel_opened[event_type].set()
            elif msg_type == "ERROR":
                raise DXLinkError(message.get("message", message))
            # SETUP / KEEPALIVE / FEED_CONFIG / CHANNEL_CLOSED: nothing to do.

    def _event_type_for_channel(self, channel: int) -> str:
        return next(et for et, ch in self._channels.items() if ch == channel)

    def _handle_feed_data(self, channel: int, data: list) -> None:
        event_type = self._event_type_for_channel(channel)
        fields = EVENT_FIELDS[event_type]
        queue = self._queues[event_type]

        if data and isinstance(data[0], dict):
            # FULL format — not what we request, but handle it defensively.
            for event_dict in data:
                queue.put_nowait(event_dict)
            return

        # COMPACT format: [eventTypeName, [flat values, repeated per event]]
        flat_values = data[1]
        width = len(fields)
        for offset in range(0, len(flat_values), width):
            values = flat_values[offset : offset + width]
            queue.put_nowait(dict(zip(fields, values)))

    async def _open_channel(self, event_type: str, refresh_interval: float) -> None:
        channel = self._next_channel
        self._next_channel += 2
        self._channels[event_type] = channel
        self._channel_opened[event_type] = asyncio.Event()
        self._queues[event_type] = asyncio.Queue()

        await self._send(
            {
                "type": "CHANNEL_REQUEST",
                "channel": channel,
                "service": "FEED",
                "parameters": {"contract": "AUTO"},
            }
        )
        await asyncio.wait_for(self._channel_opened[event_type].wait(), timeout=HANDSHAKE_TIMEOUT)

        await self._send(
            {
                "type": "FEED_SETUP",
                "channel": channel,
                "acceptAggregationPeriod": refresh_interval,
                "acceptDataFormat": "COMPACT",
                "acceptEventFields": {event_type: EVENT_FIELDS[event_type]},
            }
        )

    async def subscribe(
        self, event_type: str, symbols: str | Iterable[str], refresh_interval: float = 0.1
    ) -> None:
        """Subscribe to `event_type` events for the given symbols, opening
        a channel for that event type on first use.

        event_type: one of 'Quote', 'Trade', 'Greeks', 'Summary'.
        symbols: dxFeed streamer-symbol(s), e.g. './ESZ4 EW4U4 240920P4700'
            — see TastytradeClient.get_future_option_chain()'s
            'streamer-symbol' field.
        refresh_interval: seconds between updates for this event type;
            fixed once the channel is opened (first subscribe call).
        """
        if event_type not in EVENT_FIELDS:
            raise ValueError(f"Unsupported event type {event_type!r}; supported: {sorted(EVENT_FIELDS)}")
        if isinstance(symbols, str):
            symbols = [symbols]

        if event_type not in self._channels:
            await self._open_channel(event_type, refresh_interval)

        await self._send(
            {
                "type": "FEED_SUBSCRIPTION",
                "channel": self._channels[event_type],
                "add": [{"symbol": s, "type": event_type} for s in symbols],
            }
        )

    async def unsubscribe(self, event_type: str, symbols: str | Iterable[str]) -> None:
        if isinstance(symbols, str):
            symbols = [symbols]
        await self._send(
            {
                "type": "FEED_SUBSCRIPTION",
                "channel": self._channels[event_type],
                "remove": [{"symbol": s, "type": event_type} for s in symbols],
            }
        )

    async def listen(self, event_type: str) -> AsyncIterator[dict]:
        """Yield parsed events of `event_type` as they arrive. Call
        subscribe() first — otherwise this waits on a queue nothing feeds."""
        queue = self._queues[event_type]
        while True:
            yield await queue.get()

    async def get_event(self, event_type: str) -> dict:
        """Pull a single parsed event of `event_type` from the queue."""
        return await self._queues[event_type].get()
