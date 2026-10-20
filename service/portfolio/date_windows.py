"""How far around a requested date range to fetch transactions, so a trade
whose open (or close) falls just outside the range can still be matched.

The windows are named here rather than scattered as magic numbers:
  OPTION_LOOKBACK_DAYS / OPTION_LOOKFORWARD_DAYS   options matcher padding
  EQUITY_LOOKBACK_DAYS                              equities/futures sit open longer
  MAX_SPAN_DAYS                                     Schwab rejects requests over a year

How far back open futures / futures-option positions are rebuilt from
history is an application setting instead: positions.open_lookback_days in
config/app.properties (open_position_lookback_days() below)."""

import logging
from datetime import timedelta
from typing import Dict

from utils.app_config import get_config
from utils.utils import get_date_object

OPTION_LOOKBACK_DAYS = 30
OPTION_LOOKFORWARD_DAYS = 5
EQUITY_LOOKBACK_DAYS = 180
MAX_SPAN_DAYS = 364


def open_position_lookback_days() -> int:
    """Futures / futures-option positions are rebuilt from this many days
    of history — anything opened earlier isn't seen."""
    return get_config()["positions.open_lookback_days"]

logger = logging.getLogger(__name__)


def expand_date_range(start_date: str, end_date: str,
                       lookback_days: int = OPTION_LOOKBACK_DAYS,
                       lookforward_days: int = OPTION_LOOKFORWARD_DAYS,
                       max_span_days: int = MAX_SPAN_DAYS) -> Dict[str, str]:
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
        lookback_days (int): Number of days to look back
        lookforward_days (int): Number of days to look forward
        max_span_days (int): Hard cap on the total expanded span

    Returns:
        dict: Expanded date range with keys 'start_date' and 'end_date'
    """
    start_date_obj = get_date_object(start_date)
    end_date_obj = get_date_object(end_date)

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
