"""The real app (api.app) on sample brokers, for the UI check.

    uv run python -m scripts.ui_check.demo_server [--port 8765]

Every broker seam is swapped for scripts/ui_check/demo_data.py — the
Portfolio registry's "schwab" entry, the Market routes' services, the Schwab
connection status and the Analyze page's live chain socket — so routing,
validation and response shapes are the app's own while no broker is called.
It runs on a throwaway users database in a temp folder, with no broker, AI or
FRED credentials (the real .env is never read), and logs in as demo / demo-pass.

Requires a build: cd frontend && npm run build.
"""

import argparse
import os
import tempfile

DEMO_USER, DEMO_PASSWORD = "demo", "demo-pass-123"

_tmp = tempfile.mkdtemp(prefix="ui-check-")
# Set before api.app runs load_dotenv(), which never overrides what's set:
# a blank value keeps the real .env's credentials out of this process.
os.environ.update({
    "SECRET_KEY": "ui-check-only", "DB_PATH": os.path.join(_tmp, "users.db"),
    "TOKEN_FILE": os.path.join(_tmp, "token.json"), "ADMIN_USERNAME": DEMO_USER, "ADMIN_PASSWORD": DEMO_PASSWORD,
    "TOKEN_ENCRYPTION_KEY": "", "APP_PROPERTIES": "", "FLY_APP_NAME": "",
    "SCHWAB_APP_KEY": "", "SCHWAB_APP_SECRET": "", "TASTY_CLIENT_ID": "", "TASTY_CLIENT_SECRET": "",
    "TASTY_REFRESH_TOKEN": "", "OPENAI_API_KEY": "", "FRED_API_KEY": "",
})

import api.auth
from api.market import stream
from scripts.ui_check import demo_data
from service.portfolio import providers

providers.register(providers.PortfolioBroker("schwab", "Schwab", demo_data.DemoPositions, demo_data.DemoTransactions))


class _Connected:
    """Settings' and RequireSchwab's view of the Schwab connection."""

    def __init__(self, *_):
        pass

    def has_tokens(self):
        return True

    def refresh_token_expires_at(self):
        import time
        return time.time() + 5 * 86400


api.auth.create_token_provider = _Connected


class _QuietStreamer:
    """Stands in for DXLink on the Analyze page's socket: the chain snapshot
    is sent, then no live quotes follow."""

    def __init__(self, *_):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def subscribe(self, *_):
        return None

    async def listen(self, *_):
        import asyncio
        while True:
            await asyncio.sleep(3600)
            yield {}


class _StreamClient:
    def resolve_underlying_streamer_symbol(self, symbol):
        return symbol

    def get_quote_token(self):
        return "demo"


stream.TastytradeOptionChainProvider = demo_data.DemoChainProvider
stream.DXLinkStreamer = _QuietStreamer
stream.get_shared_client = _StreamClient

from api import users
from api.app import app
from api.market import chains, events, history, quotes, screener, strategy, watchlist
from service.market import MarketService


def _market():
    return MarketService(chain_provider=demo_data.DemoChainProvider(), client=demo_data.DemoMarketClient())


for module in (chains, screener, strategy, history):
    app.dependency_overrides[module.get_service] = _market
app.dependency_overrides[quotes.get_service] = demo_data.DemoQuotes
app.dependency_overrides[watchlist.get_service] = demo_data.DemoWatchlist
app.dependency_overrides[events.get_service] = demo_data.DemoEvents


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    users.init_db()
    demo = users.get_user_by_username(DEMO_USER)
    users.set_profile(demo.id, "Demo", "Trader", None)

    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
