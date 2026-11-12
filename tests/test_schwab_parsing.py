"""How Schwab's records are classified (service/portfolio/providers/schwab.py).
Descriptions are the exact text Schwab uses."""

import pytest

from service.portfolio.providers.schwab import SchwabTransactionProvider
from utils.utils import get_date_object

classify = SchwabTransactionProvider._identify_close_event


@pytest.mark.parametrize("raw_type, description, expected", [
    # Equity options: closes arrive as RECEIVE_AND_DELIVER
    ("RECEIVE_AND_DELIVER", "Removed due to Expiration PUT ISHR RUSSELL 2000 $245 EXP 04/02/26", "EXPIRATION"),
    ("RECEIVE_AND_DELIVER", "Removed due to Assignment CALL INVESCO QQQ TR $610 EXP 04/13/26", "ASSIGNMENT"),
    ("RECEIVE_AND_DELIVER", "Removed due to Exercise PUT AIRBNB INC $126 EXP 11/07/25", "ASSIGNMENT"),
    # Futures options: closes arrive as ordinary TRADEs at $0
    ("TRADE", "Exercise, future settle 2.0 of /NQZ26 XCME 20 16 Oct 2026 29500.0 PUT", "EXERCISE"),
    ("TRADE", "Removal of option due to expiration of /ESZ26 XCME 50 16 Oct 2026 7650.0 PUT", "EXPIRATION"),
    # A normal trade is not a close event
    ("TRADE", None, None),
    ("TRADE", "Sell to open", None),
])
def test_close_event_classification(raw_type, description, expected):
    assert classify(raw_type, description, "SYM") == expected


@pytest.mark.parametrize("symbol, root", [
    ("/ESU26:XCME", "ES"),
    ("/NQU26:XCME", "NQ"),
    (".QN4M26:XCME", "NQ"),
    (".E3DM26_P7050:XCME", "ES"),
    ("AAPL", "AAPL"),
])
def test_futures_root_normalization(symbol, root):
    provider = SchwabTransactionProvider(client=object())  # no network
    assert provider.normalize_futures_symbol(symbol) == root


def _activity(activity_id, date, symbol, asset_type, amount, price, effect):
    from types import SimpleNamespace
    item = SimpleNamespace(
        instrument=SimpleNamespace(symbol=symbol, assetType=asset_type),
        amount=amount, price=price, cost=-amount * price, positionEffect=effect,
    )
    return SimpleNamespace(activityId=activity_id, tradeDate=get_date_object(date), type="TRADE", transferItems=[item])


class _FakeClient:
    """Serves fixed records, recording each requested window."""

    def __init__(self, records):
        self.records, self.windows = records, []

    def fetch_transactions(self, start_date, end_date):
        self.windows.append((start_date, end_date))
        start, end = get_date_object(start_date), get_date_object(end_date)
        return [r for r in self.records if start <= r.tradeDate <= end]


def test_etf_fills_count_as_equity():
    client = _FakeClient([_activity(1, "2026-09-18", "IWM", "COLLECTIVE_INVESTMENT", 300.0, 290.0, "CLOSING")])
    [leg] = SchwabTransactionProvider(client=client).fetch_equity_future_legs("2026-09-01", "2026-09-30")
    assert (leg["symbol"], leg["asset_type"], leg["position_effect"]) == ("IWM", "EQUITY", "CLOSING")


def test_shares_assigned_on_a_friday_are_dated_that_friday():
    # Booked Saturday (2026-10-31) with Monday's tradeDate.
    shares = _activity(1, "2026-11-02", "QQQ", "COLLECTIVE_INVESTMENT", 1100.0, 720.0, "CLOSING")
    shares.time = get_date_object("2026-10-31")
    client = _FakeClient([shares])
    [leg] = SchwabTransactionProvider(client=client).fetch_equity_future_legs("2026-10-01", "2026-11-05")
    assert leg["date"] == "2026-10-30"


def test_a_stock_fill_after_midnight_utc_keeps_its_trade_date():
    shares = _activity(1, "2026-10-30", "QQQ", "COLLECTIVE_INVESTMENT", 100.0, 700.0, "OPENING")
    shares.time = get_date_object("2026-10-31")
    client = _FakeClient([shares])
    [leg] = SchwabTransactionProvider(client=client).fetch_equity_future_legs("2026-10-01", "2026-11-05")
    assert leg["date"] == "2026-10-30"


def test_a_futures_fill_keeps_its_trade_date():
    # The evening session belongs to the next trade date.
    future = _activity(1, "2026-10-28", "/NQZ26:XCME", "FUTURE", 1.0, 29000.0, "OPENING")
    future.time = get_date_object("2026-10-27")
    client = _FakeClient([future])
    [leg] = SchwabTransactionProvider(client=client).fetch_equity_future_legs("2026-10-01", "2026-11-05")
    assert leg["date"] == "2026-10-28"


def test_long_range_is_fetched_a_year_at_a_time_without_duplicates():
    # Record 2 sits on the boundary date, so both windows return it.
    client = _FakeClient([
        _activity(1, "2025-02-01", "CRM", "EQUITY", 200.0, 250.0, "OPENING"),
        _activity(2, "2026-01-01", "CRM", "EQUITY", 100.0, 240.0, "OPENING"),
        _activity(3, "2026-09-08", "CRM", "EQUITY", -200.0, 200.0, "CLOSING"),
    ])
    legs = SchwabTransactionProvider(client=client).fetch_equity_future_legs("2025-01-02", "2026-10-23")
    assert len(client.windows) == 2
    assert all((get_date_object(e) - get_date_object(s)).days <= 364 for s, e in client.windows)
    assert [leg["date"] for leg in legs] == ["2025-02-01", "2026-01-01", "2026-09-08"]


def test_income_and_fees_are_read_from_dividend_and_trade_records():
    from types import SimpleNamespace
    when = get_date_object("2026-09-28")
    records = [
        SimpleNamespace(activityId=1, tradeDate=when, type="DIVIDEND_OR_INTEREST", description="SCHWAB1 INT 08/28-09/28", netAmount=3890.15, transferItems=[]),
        SimpleNamespace(activityId=2, tradeDate=when, type="DIVIDEND_OR_INTEREST", description="INTEREST 02/26THRU 03/29", netAmount=-596.92, transferItems=[]),
        SimpleNamespace(activityId=3, tradeDate=when, type="DIVIDEND_OR_INTEREST", description="NIKE INC CLASS B", netAmount=164.0, transferItems=[]),
        SimpleNamespace(activityId=4, tradeDate=when, type="DIVIDEND_OR_INTEREST", description="STATE STREET SPDR S&P 500 ETF TRUST", netAmount=-2474.57, transferItems=[]),
        SimpleNamespace(activityId=5, tradeDate=when, type="DIVIDEND_OR_INTEREST", description="SCHWAB US TREASURY MONEY INVESTOR", netAmount=523.54, transferItems=[]),
        SimpleNamespace(activityId=6, tradeDate=when, type="TRADE", description=None, netAmount=-661.81, transferItems=[
            SimpleNamespace(feeType=None, cost=-660.0, instrument=SimpleNamespace(assetType="OPTION")),
            SimpleNamespace(feeType="COMMISSION", cost=-1.75, instrument=SimpleNamespace(assetType="CURRENCY")),
            SimpleNamespace(feeType="OPT_REG_FEE", cost=-0.06, instrument=SimpleNamespace(assetType="CURRENCY")),
        ]),
        SimpleNamespace(activityId=7, tradeDate=when, type="JOURNAL", description="JOURNAL TO 1", netAmount=-100000.0, transferItems=[]),
    ]
    rows = SchwabTransactionProvider(client=_FakeClient(records)).fetch_income_and_fees("2026-09-01", "2026-09-30")
    assert [(r["kind"], r["category"], r["amount"]) for r in rows] == [
        ("INCOME", "INTEREST", 3890.15),
        ("INCOME", "MARGIN_INTEREST", -596.92),
        ("INCOME", "DIVIDEND", 164.0),
        ("INCOME", "SHORT_DIVIDEND", -2474.57),
        ("INCOME", "MONEY_FUND_DIVIDEND", 523.54),
        ("FEE", "COMMISSION", -1.75),
        ("FEE", "OPT_REG_FEE", -0.06),
    ]


def test_a_share_transfer_is_not_a_fill():
    from types import SimpleNamespace
    transfer = SimpleNamespace(activityId=9, tradeDate=get_date_object("2026-10-05"), type="RECEIVE_AND_DELIVER", transferItems=[
        SimpleNamespace(instrument=SimpleNamespace(symbol="META", assetType="EQUITY"), amount=90.0, price=0.0, cost=0.0, positionEffect=None),
    ])
    assert SchwabTransactionProvider(client=_FakeClient([transfer])).fetch_equity_future_legs("2026-10-01", "2026-10-31") == []


def test_account_list_asks_for_balances_only():
    from broker.schwab.clients.accounts import Accounts

    calls = []

    class StandIn(Accounts):
        def _fetch_data(self, url=None, params=None, **kwargs):
            calls.append((url.rsplit("/v1", 1)[1], params))
            if url.endswith("/accountNumbers"):
                return [{"accountNumber": "12345678", "hashValue": "H1"}]
            return [{"securitiesAccount": {"accountNumber": "12345678", "type": "MARGIN",
                                           "currentBalances": {"liquidationValue": 52340.17}}}]

    accounts = StandIn(token_provider=object()).list_accounts()
    assert accounts == [{"accountNumber": "12345678", "hashValue": "H1", "type": "MARGIN", "liquidationValue": 52340.17}]
    # Without fields=positions: the picker doesn't download every holding.
    assert ("/accounts", None) in calls


def test_only_executions_with_an_order_behind_them_were_placed():
    from types import SimpleNamespace
    when = get_date_object("2026-09-28")

    def leg(asset, effect, **instrument):
        return SimpleNamespace(instrument=SimpleNamespace(assetType=asset, symbol=instrument.pop("symbol", "X"), **instrument),
                               positionEffect=effect, amount=-1.0, price=2.5)
    put = dict(symbol="SPY   261016P00650000", underlyingSymbol="SPY", putCall="PUT", strikePrice=650.0,
               expirationDate=get_date_object("2026-10-16"))
    records = [
        # A two-leg order with its commission line: two placed executions
        SimpleNamespace(activityId=1, tradeDate=when, time=None, type="TRADE", orderId=77, description=None,
                        transferItems=[leg("OPTION", "OPENING", **put), leg("OPTION", "OPENING", **put), leg("CURRENCY", None)]),
        # A futures option's expiry and the shares from an assignment: booked as TRADEs, no order
        SimpleNamespace(activityId=2, tradeDate=when, time=None, type="TRADE", orderId=None,
                        description="Removal of option due to expiration of /ESZ26 XCME", transferItems=[leg("OPTION", "CLOSING", **put)]),
        SimpleNamespace(activityId=3, tradeDate=when, time=None, type="TRADE", orderId=None,
                        description="INVESCO QQQ TR", transferItems=[leg("COLLECTIVE_INVESTMENT", "OPENING", symbol="QQQ")]),
        # An equity option's assignment is a transfer, not an execution at all
        SimpleNamespace(activityId=4, tradeDate=when, time=None, type="RECEIVE_AND_DELIVER", orderId=None,
                        description="Removed due to Assignment", transferItems=[leg("OPTION", "CLOSING", **put)]),
    ]
    rows = SchwabTransactionProvider(client=_FakeClient(records)).fetch_executions("2026-09-01", "2026-09-30")
    assert [(r["asset_class"], r["placed"], r["order_id"]) for r in rows] == [
        ("OPTION", True, "77"), ("OPTION", True, "77"), ("OPTION", False, None), ("ETF", False, None),
    ]
    assert (rows[0]["underlying"], rows[0]["strike"], rows[0]["expiration"], rows[0]["option_type"]) == ("SPY", 650.0, "2026-10-16", "PUT")


class _TwoAccountClient:
    """Two accounts, each with its own records, served by account hash."""

    def __init__(self, by_hash):
        self.by_hash = by_hash

    def list_accounts(self):
        return [{"accountNumber": f"N{h}", "hashValue": h} for h in self.by_hash]

    def fetch_transactions(self, start_date, end_date, account_hash=None):
        return list(self.by_hash[account_hash or next(iter(self.by_hash))])


@pytest.fixture
def all_accounts():
    from broker.request_context import ALL_ACCOUNTS, _selected_account
    token = _selected_account.set(ALL_ACCOUNTS)
    yield
    _selected_account.reset(token)


def test_all_accounts_reads_every_account_and_matches_within_each(all_accounts):
    from service.portfolio import TransactionService
    from service.portfolio.equity_matching import combine_equity_lots, match_equity_fills
    # SPY bought in account A, sold in account B: two open lots, not a trade.
    client = _TwoAccountClient({
        "A": [_activity(1, "2026-09-01", "SPY", "COLLECTIVE_INVESTMENT", 100, 650.0, "OPENING")],
        "B": [_activity(2, "2026-09-02", "SPY", "COLLECTIVE_INVESTMENT", -100, 660.0, "CLOSING")],
    })
    provider = SchwabTransactionProvider(client=client)
    legs = provider.fetch_equity_future_legs("2026-09-01", "2026-09-30")
    assert [(leg["account"], leg["amount"]) for leg in legs] == [("A", 100.0), ("B", -100.0)]
    assert not any(t["closed"] for t in match_equity_fills(combine_equity_lots(legs)))
    assert len(provider.fetch_raw_transactions("2026-09-01", "2026-09-30")) == 2


def test_one_account_chosen_reads_only_it():
    client = _TwoAccountClient({"A": [_activity(1, "2026-09-01", "SPY", "EQUITY", 100, 650.0, "OPENING")], "B": []})
    legs = SchwabTransactionProvider(client=client).fetch_equity_future_legs("2026-09-01", "2026-09-30")
    assert [leg["account"] for leg in legs] == [None]


def test_all_accounts_balances_add_up_and_holdings_merge():
    from service.portfolio.providers.schwab import _combine_balances, _combine_positions
    balances = _combine_balances([
        {"cash_balance": 100.0, "net_liquidity": 1_330_093.0, "available_funds": None},
        {"cash_balance": 50.0, "net_liquidity": 653_047.0, "available_funds": 10.0},
        None,
    ])
    assert balances == {"cash_balance": 150.0, "net_liquidity": 1_983_140.0, "available_funds": 10.0}

    def pos(qty, avg, pl):
        return {"asset_type": "EQUITY", "symbol": "QQQ", "long_quantity": qty, "short_quantity": 0,
                "average_price": avg, "tax_lot_long_price": avg, "tax_lot_short_price": None,
                "long_open_pl": pl, "short_open_pl": 0, "maintenance_requirement": 1.0}
    [qqq] = _combine_positions([pos(100, 600.0, 10.0), pos(300, 640.0, 20.0)])
    assert qqq["long_quantity"] == 400
    assert qqq["average_price"] == pytest.approx(630.0)
    assert (qqq["long_open_pl"], qqq["maintenance_requirement"]) == (30.0, 2.0)
