"""How far around a requested date range to fetch transactions, so a trade
whose open (or close) falls just outside the range can still be matched.

The padding is set in config/app.properties (transactions.option_lookback_days,
transactions.option_lookforward_days, transactions.equity_lookback_days),
as is how far back open futures / futures-option positions are rebuilt
(positions.open_lookback_days). MAX_SPAN_DAYS stays here: it's Schwab's
one-year request limit, not a preference."""

import logging
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from utils.app_config import get_config
from utils.utils import get_date_object

MAX_SPAN_DAYS = 364


def equity_lookback_days() -> int:
    """How far before a range equity/futures round-trips look for their open."""
    return get_config()["transactions.equity_lookback_days"]


def open_position_lookback_days() -> int:
    """Futures / futures-option positions are rebuilt from this many days
    of history — anything opened earlier isn't seen."""
    return get_config()["positions.open_lookback_days"]

logger = logging.getLogger(__name__)


def expand_date_range(start_date: str, end_date: str,
                       lookback_days: Optional[int] = None,
                       lookforward_days: Optional[int] = None,
                       max_span_days: Optional[int] = MAX_SPAN_DAYS) -> Dict[str, str]:
    """
    Expand a date range by a specified number of days in both directions.

    Schwab's transaction API rejects any request spanning more than a year,
    so the requested padding is shrunk (lookback first, since finding the
    opening trade matters more than a few extra days of lookforward) to keep
    the expanded span within `max_span_days` when the caller's own range is
    already large.

    Args:
        start_date (str): Original start date in YYYY-MM-DD format
        end_date (str): Original end date in YYYY-MM-DD format
        lookback_days (int): Number of days to look back (default:
            transactions.option_lookback_days)
        lookforward_days (int): Number of days to look forward (default:
            transactions.option_lookforward_days)
        max_span_days (int): Hard cap on the total expanded span; None for
            no cap (the caller fetches through split_date_range)

    Returns:
        dict: Expanded date range with keys 'start_date' and 'end_date'
    """
    # Defaults read at call time (not def time) so they follow the config.
    if lookback_days is None:
        lookback_days = get_config()["transactions.option_lookback_days"]
    if lookforward_days is None:
        lookforward_days = get_config()["transactions.option_lookforward_days"]
    start_date_obj = get_date_object(start_date)
    end_date_obj = get_date_object(end_date)

    if max_span_days is not None:
        user_span_days = (end_date_obj - start_date_obj).days
        available_padding = max(max_span_days - user_span_days, 0)
        # Lookback claims the padding first (per the docstring above) — it was
        # backwards here: lookforward was consuming the budget first, leaving
        # lookback with the scraps whenever the caller's own span already ate
        # most of max_span_days.
        lookback_days = min(lookback_days, available_padding)
        lookforward_days = min(lookforward_days, max(available_padding - lookback_days, 0))

    expanded_start_date = (start_date_obj - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    expanded_end_date = (end_date_obj + timedelta(days=lookforward_days)).strftime('%Y-%m-%d')

    return {
        "start_date": expanded_start_date,
        "end_date": expanded_end_date
    }


def split_date_range(start_date: str, end_date: str,
                     max_span_days: int = MAX_SPAN_DAYS) -> List[Tuple[str, str]]:
    """Split start_date..end_date into consecutive windows of at most
    max_span_days, for a range longer than one Schwab request allows. Each
    window starts where the previous one ended (the request's end is
    midnight of end_date), so no day falls between two windows."""
    windows = []
    cursor = get_date_object(start_date)
    end = get_date_object(end_date)
    while True:
        window_end = min(cursor + timedelta(days=max_span_days), end)
        windows.append((cursor.strftime('%Y-%m-%d'), window_end.strftime('%Y-%m-%d')))
        if window_end >= end:
            return windows
        cursor = window_end
