"""The market's calendar date.

US options and futures expire and settle on New York dates. The server's
own clock is UTC on Fly, which runs a day ahead of New York every evening
after 8pm ET, so "today" for days-to-expiry and lookback windows must come
from here, not date.today() / datetime.now().
"""

from datetime import date, datetime

import pytz

MARKET_TZ = pytz.timezone("America/New_York")


def market_today() -> date:
    """Today's date in New York."""
    return datetime.now(MARKET_TZ).date()
