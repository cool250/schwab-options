"""
Backward-compatible re-export of the broker-neutral exception hierarchy —
see broker/exceptions.py for the actual definitions and docstrings.

These used to be defined here, Schwab-specific in name only (the hierarchy
was always meant to be broker-neutral, per its own original docstring).
Moved so a non-Schwab provider (e.g. a future TastytradeAccountProvider)
can raise/import them without an odd `from broker.schwab.exceptions import
...`. `from X import Y` preserves class identity, so every existing
`except BrokerError` (or `BrokerAuthError`, etc.) written against this
module path still catches the exact same runtime exceptions — no caller
needs to change.
"""

from broker.exceptions import BrokerError, BrokerAuthError, BrokerAPIError, BrokerValidationError

__all__ = ["BrokerError", "BrokerAuthError", "BrokerAPIError", "BrokerValidationError"]
