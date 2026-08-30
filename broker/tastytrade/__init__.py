"""broker.tastytrade: a Tastytrade REST client + DXLink WebSocket streamer.

    from broker.tastytrade import TastytradeClient, DXLinkStreamer

    client = TastytradeClient.from_config()  # TASTY_CLIENT_SECRET / TASTY_REFRESH_TOKEN env vars
    chain = client.get_options_chain("AAPL", dte=30, option_type="call", num_strikes=10)
    quotes = client.get_chain_quotes(chain)

See client.py and dxlink_streamer.py for full API docs.
"""

from .client import TastytradeAPIError, TastytradeClient
from .dxlink_streamer import DXLinkError, DXLinkStreamer

__all__ = [
    "TastytradeClient",
    "TastytradeAPIError",
    "DXLinkStreamer",
    "DXLinkError",
]

__version__ = "0.1.0"
