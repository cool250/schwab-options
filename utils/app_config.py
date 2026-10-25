"""Application-level choices from config/app.properties (or the file named
by APP_PROPERTIES).

SETTINGS below is the schema: every allowed key with its type, default and
(optionally) allowed values. A key missing from the file takes its
default; an unknown key or a value that doesn't parse raises
AppConfigError, so a typo stops the app at startup instead of being
silently ignored. Adding a setting = one SETTINGS entry plus a commented
line in config/app.properties.

Read with get_config()["trades.group_ratio_spreads"]. The file is read
once and cached; reload_config() re-reads it (tests, or a manual reload).
Not for secrets — those stay in environment variables.
"""

import os
import threading
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "app.properties"

# key -> (type, default, allowed values or None, minimum or None)
SETTINGS: dict[str, tuple[type, Any, Optional[tuple], Optional[int]]] = {
    "trades.group_ratio_spreads": (bool, True, None, None),
    "transactions.default_view": (str, "realized", ("realized", "unrealized", "both"), None),
    "positions.open_lookback_days": (int, 30, None, 1),
    "transactions.option_lookback_days": (int, 30, None, 1),
    "transactions.option_lookforward_days": (int, 5, None, 0),
    "transactions.equity_lookback_days": (int, 365, None, 1),
    "copilot.history_days": (int, 90, None, 1),
    "home.futures_margin_pct": (int, 11, None, 1),
    "home.available_funds": (int, 0, None, 0),
    "home.take_profit_pct": (int, 75, None, 1),
    "home.expiring_days": (int, 7, None, 1),
    "home.at_risk_pct": (int, 2, None, 0),
    "home.concentration_pct": (int, 25, None, 1),
    "home.idea_max_dte": (int, 7, None, 0),
    "home.idea_min_delta_pct": (int, 10, None, 0),
    "home.idea_max_delta_pct": (int, 30, None, 1),
}

# Settings the browser needs (served by GET /api/config). Others stay
# server-side.
PUBLIC_SETTINGS = (
    "trades.group_ratio_spreads", "transactions.default_view",
    # The Home page's rules (all applied in the browser).
    "home.futures_margin_pct", "home.available_funds", "home.take_profit_pct", "home.expiring_days", "home.at_risk_pct",
    "home.concentration_pct", "home.idea_max_dte", "home.idea_min_delta_pct", "home.idea_max_delta_pct",
)

_TRUE, _FALSE = ("true", "yes", "1", "on"), ("false", "no", "0", "off")

_lock = threading.Lock()
_config: Optional[dict[str, Any]] = None


class AppConfigError(ValueError):
    pass


def _convert(key: str, raw: str) -> Any:
    type_, _default, allowed, minimum = SETTINGS[key]
    value: Any
    if type_ is bool:
        if raw.lower() in _TRUE:
            value = True
        elif raw.lower() in _FALSE:
            value = False
        else:
            raise AppConfigError(f"{key}: expected true or false, got {raw!r}")
    elif type_ is int:
        try:
            value = int(raw)
        except ValueError:
            raise AppConfigError(f"{key}: expected a whole number, got {raw!r}") from None
        if minimum is not None and value < minimum:
            raise AppConfigError(f"{key}: must be at least {minimum}, got {value}")
    else:
        value = raw
    if allowed is not None and value not in allowed:
        raise AppConfigError(f"{key}: must be one of {', '.join(allowed)}, got {raw!r}")
    return value


def parse(text: str, source: str = "app.properties") -> dict[str, Any]:
    """Settings from properties-file `text`, defaults filled in."""
    values = {key: spec[1] for key, spec in SETTINGS.items()}
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        sep = min((i for i in (line.find("="), line.find(":")) if i >= 0), default=-1)
        if sep < 0:
            raise AppConfigError(f"{source}:{number}: expected key=value, got {line!r}")
        key, raw = line[:sep].strip(), line[sep + 1 :].strip()
        if key not in SETTINGS:
            raise AppConfigError(f"{source}:{number}: unknown setting {key!r} (known: {', '.join(SETTINGS)})")
        values[key] = _convert(key, raw)
    return values


def _path() -> Path:
    return Path(os.getenv("APP_PROPERTIES") or DEFAULT_PATH)


def reload_config() -> dict[str, Any]:
    """Re-read the properties file. A missing file means all defaults; an
    explicitly configured APP_PROPERTIES that doesn't exist is an error."""
    global _config
    path = _path()
    if path.is_file():
        values = parse(path.read_text(encoding="utf-8"), source=str(path))
    elif os.getenv("APP_PROPERTIES"):
        raise AppConfigError(f"APP_PROPERTIES points to {path}, which doesn't exist")
    else:
        values = parse("")
    with _lock:
        _config = values
    return values


def get_config() -> dict[str, Any]:
    with _lock:
        cached = _config
    return cached if cached is not None else reload_config()


def public_config() -> dict[str, Any]:
    config = get_config()
    return {key: config[key] for key in PUBLIC_SETTINGS}
