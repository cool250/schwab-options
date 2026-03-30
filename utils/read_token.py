"""
Backward-compatible token access helpers.

These thin wrappers delegate to :class:`broker.token_provider.EnvTokenProvider`
so that callers outside the broker SDK (e.g. ``broker/refresh_token.py``) do
not need to be changed.

Prefer using :class:`broker.token_provider.TokenProvider` directly for new code.
"""

import logging

logger = logging.getLogger(__name__)


def _provider():
    from broker.token_provider import EnvTokenProvider
    return EnvTokenProvider()


def save_token(data: dict) -> None:
    _provider().save_tokens(data)


def read_token() -> dict:
    provider = _provider()
    return {
        "access_token": provider.get_access_token(),
        "refresh_token": provider.get_refresh_token(),
    }


def get_response_token() -> str:
    return _provider().get_refresh_token()


def get_access_token() -> str:
    return _provider().get_access_token()
