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
    "home.take_profit_pct": (int, 75, None, 1),
    "home.idea_max_dte": (int, 7, None, 0),
    "home.stress_iv_rise": (int, 20, None, 0),
    "home.idea_crash_pct": (int, 5, None, 1),
    "home.event_crash_pct": (int, 8, None, 1),
    "wheel.aggressive_max_leverage_pct": (int, 150, None, 1),
    "wheel.defensive_min_leverage_pct": (int, 300, None, 1),
    "wheel.loss_budget_pct": (int, 25, None, 0),
    # Wind-down call ratios on long futures may strike their short calls up
    # to this percent below the cheapest open lot's trade price.
    "wheel.ratio_call_max_below_entry_pct": (int, 5, None, 0),
    # Delta ranges for new short options per mode, in hundredths ("20-30"
    # = 0.20-0.30). Defensive mode sells no new puts, so it has no put range.
    "wheel.aggressive_put_delta_pct": (list, [20, 30], None, 0),
    "wheel.neutral_put_delta_pct": (list, [10, 20], None, 0),
    "wheel.aggressive_call_delta_pct": (list, [25, 30], None, 0),
    "wheel.neutral_call_delta_pct": (list, [20, 30], None, 0),
    "wheel.defensive_call_delta_pct": (list, [30, 40], None, 0),
    # FOMC decision days (the meeting's second day), comma-separated.
    "events.fomc_dates": (str, "2026-10-28,2026-12-09,2027-01-27,2027-03-17,2027-04-28,2027-06-09,2027-07-28,2027-09-15,2027-10-27,2027-12-08", None, None),
}

# Settings the browser needs (served by GET /api/config). Others stay
# server-side.
PUBLIC_SETTINGS = (
    "trades.group_ratio_spreads", "transactions.default_view",
    # The Home page's rules (all applied in the browser).
    "home.futures_margin_pct", "home.take_profit_pct",
    "home.idea_max_dte",
    "home.stress_iv_rise", "home.idea_crash_pct", "home.event_crash_pct",
    # The options-wheel rules, for Home's New Income ideas (utils/wheel.js).
    "wheel.aggressive_max_leverage_pct", "wheel.defensive_min_leverage_pct",
    "wheel.aggressive_put_delta_pct", "wheel.neutral_put_delta_pct",
    "wheel.aggressive_call_delta_pct", "wheel.neutral_call_delta_pct", "wheel.defensive_call_delta_pct",
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
    elif type_ is list:
        # A range of whole numbers, "low-high" -> [low, high].
        try:
            low, high = (int(part) for part in raw.split("-"))
        except ValueError:
            raise AppConfigError(f"{key}: expected a range like 20-30, got {raw!r}") from None
        if low > high or (minimum is not None and low < minimum):
            raise AppConfigError(f"{key}: expected low-high with low at least {minimum or 0} and not above high, got {raw!r}")
        value = [low, high]
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
