"""
Wheel strategy optimizer — recommends short OTM options to sell.

Two strategies are supported:

* **Covered Calls** — for every stock position that has ≥ 100 shares, find
  the best OTM call expiring within *max_dte* days.
* **Cash-Secured Puts** — for the tickers already held (plus any
  *extra_symbols* passed to :meth:`WheelOptimizer.optimize`), find the best
  OTM put that fits within available buying power / margin.

All recommendations are ranked by annualized return on collateral so the
highest-yield trade appears first.

Usage::

    from service.optimizer import WheelOptimizer

    recs = WheelOptimizer().optimize()
    for r in recs[:5]:
        print(r)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytz

from broker import Client
from broker.data.option_data import OptionDetail
from broker.exceptions import BrokerError
from service.position import PositionService

logger = logging.getLogger(__name__)

_EASTERN = pytz.timezone("US/Eastern")
_CONTRACT_SIZE = 100          # shares per option contract
_STRIKE_COUNT = 50


@dataclass
class OptionRecommendation:
    """A single option-selling recommendation."""
    symbol: str               # underlying ticker
    option_type: str          # "CALL" or "PUT"
    option_symbol: str        # full OCC symbol
    strike: float
    expiration_date: str
    dte: int                  # days to expiration
    premium: float            # mark price per share
    premium_total: float      # total credit for all contracts
    annualized_return: float  # % annualised return on collateral
    contracts: int            # number of contracts available
    margin_required: float    # total collateral required
    delta: float

    def __str__(self) -> str:
        return (
            f"{self.option_type:4s} {self.symbol:6s} "
            f"${self.strike:>8.2f}  exp {self.expiration_date[:10]}  "
            f"DTE={self.dte:2d}  premium=${self.premium:.3f}  "
            f"ann={self.annualized_return:.1f}%  "
            f"contracts={self.contracts}  margin=${self.margin_required:,.0f}  delta={self.delta:.2f}"
        )


class WheelOptimizer:
    """
    Suggest the best short OTM options to sell (≤ *max_dte* days to expiry).

    Parameters
    ----------
    max_dte:
        Maximum days to expiration to consider.  Defaults to 7.
    """

    def __init__(self, max_dte: int = 7) -> None:
        self._client = Client()
        self._position_svc = PositionService()
        self._max_dte = max_dte

    def optimize(self, extra_symbols: list[str] | None = None) -> list[OptionRecommendation]:
        """
        Return all viable sell recommendations ranked by annualized return.

        Parameters
        ----------
        extra_symbols:
            Additional tickers to scan for cash-secured puts beyond the
            ones already held in the portfolio.
        """
        buying_power = self._buying_power()
        stocks = self._position_svc.get_stock_position()
        stock_cost_basis = self._stock_cost_basis()

        from_date = datetime.now(_EASTERN).strftime("%Y-%m-%d")
        to_date = (datetime.now(_EASTERN) + timedelta(days=self._max_dte)).strftime("%Y-%m-%d")

        recommendations: list[OptionRecommendation] = []

        # Covered Calls — one call per 100 shares owned.
        for stock in stocks:
            qty = float(str(stock["quantity"]).replace(",", ""))
            if qty < 100:
                continue
            contracts = int(qty // 100)
            cost_basis = stock_cost_basis.get(stock["symbol"], 0.0)
            recommendations.extend(
                self._scan_calls(stock["symbol"], contracts, from_date, to_date, cost_basis)
            )

        # Cash-Secured Puts — scan held tickers plus any extras.
        put_symbols: set[str] = {s["symbol"] for s in stocks}
        if extra_symbols:
            put_symbols.update(extra_symbols)

        for symbol in sorted(put_symbols):
            recommendations.extend(
                self._scan_puts(symbol, buying_power, from_date, to_date)
            )

        recommendations.sort(key=lambda r: r.annualized_return, reverse=True)
        return recommendations

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _buying_power(self) -> float:
        """Return option buying power (falls back to cash balance)."""
        balances = self._position_svc.position
        if balances and balances.currentBalances:
            bp = balances.currentBalances.optionBuyingPower
            if bp:
                return bp
        raw = self._position_svc.get_balances()
        return raw.get("cash") or 0.0

    def _spot(self, symbol: str) -> float | None:
        try:
            quotes = self._client.get_price(symbol)
            asset = quotes.root.get(symbol)
            return asset.quote.lastPrice if asset and asset.quote else None
        except BrokerError as e:
            logger.error("Price fetch failed for %s: %s", symbol, e)
            return None

    def _stock_cost_basis(self) -> dict[str, float]:
        """Return ``{ticker: average_purchase_price}`` for all equity positions."""
        result: dict[str, float] = {}
        positions = (
            self._position_svc.position.positions
            if self._position_svc.position and self._position_svc.position.positions
            else []
        )
        for pos in positions:
            if not pos.instrument or pos.instrument.assetType not in ("EQUITY", "COLLECTIVE_INVESTMENT"):
                continue
            if pos.instrument.symbol and pos.averagePrice:
                result[pos.instrument.symbol] = pos.averagePrice
        return result

    def _scan_calls(
        self,
        symbol: str,
        contracts: int,
        from_date: str,
        to_date: str,
        cost_basis: float = 0.0,
    ) -> list[OptionRecommendation]:
        spot = self._spot(symbol)
        if spot is None:
            return []

        try:
            chain = self._client.get_chain(
                symbol, from_date, to_date, strike_count=_STRIKE_COUNT, contract_type="CALL"
            )
        except BrokerError as e:
            logger.error("Call chain failed for %s: %s", symbol, e)
            return []

        if not chain.callExpDateMap:
            return []

        best_per_expiry: dict[str, OptionRecommendation] = {}
        for exp_date, strikes in chain.callExpDateMap.items():
            for strike_str, options in strikes.items():
                strike = float(strike_str)
                if strike <= spot or strike <= cost_basis:  # skip ITM and below cost basis
                    continue
                for opt in options:
                    if not self._valid(opt):
                        continue
                    # Collateral = underlying value (covered = shares owned)
                    collateral = spot * _CONTRACT_SIZE * contracts
                    ann_return = self._ann_return(opt.mark, spot, opt.daysToExpiration)
                    existing = best_per_expiry.get(exp_date)
                    if existing is None or ann_return > existing.annualized_return:
                        best_per_expiry[exp_date] = OptionRecommendation(
                            symbol=symbol,
                            option_type="CALL",
                            option_symbol=opt.symbol,
                            strike=strike,
                            expiration_date=exp_date,
                            dte=opt.daysToExpiration,
                            premium=opt.mark,
                            premium_total=opt.mark * _CONTRACT_SIZE * contracts,
                            annualized_return=ann_return,
                            contracts=contracts,
                            margin_required=collateral,
                            delta=opt.delta,
                        )
        return list(best_per_expiry.values())

    def _scan_puts(
        self,
        symbol: str,
        buying_power: float,
        from_date: str,
        to_date: str,
    ) -> list[OptionRecommendation]:
        spot = self._spot(symbol)
        if spot is None:
            return []

        try:
            chain = self._client.get_chain(
                symbol, from_date, to_date, strike_count=_STRIKE_COUNT, contract_type="PUT"
            )
        except BrokerError as e:
            logger.error("Put chain failed for %s: %s", symbol, e)
            return []

        if not chain.putExpDateMap:
            return []

        best_per_expiry: dict[str, OptionRecommendation] = {}
        for exp_date, strikes in chain.putExpDateMap.items():
            for strike_str, options in strikes.items():
                strike = float(strike_str)
                if strike >= spot:                # skip ITM
                    continue
                margin_per_contract = strike * _CONTRACT_SIZE
                contracts = int(buying_power // margin_per_contract)
                if contracts < 1:
                    continue
                for opt in options:
                    if not self._valid(opt):
                        continue
                    ann_return = self._ann_return(opt.mark, strike, opt.daysToExpiration)
                    existing = best_per_expiry.get(exp_date)
                    if existing is None or ann_return > existing.annualized_return:
                        best_per_expiry[exp_date] = OptionRecommendation(
                            symbol=symbol,
                            option_type="PUT",
                            option_symbol=opt.symbol,
                            strike=strike,
                            expiration_date=exp_date,
                            dte=opt.daysToExpiration,
                            premium=opt.mark,
                            premium_total=opt.mark * _CONTRACT_SIZE * contracts,
                            annualized_return=ann_return,
                            contracts=contracts,
                            margin_required=margin_per_contract * contracts,
                            delta=opt.delta,
                        )
        return list(best_per_expiry.values())

    def _valid(self, opt: OptionDetail) -> bool:
        return (
            opt.mark is not None
            and opt.mark > 0
            and opt.delta is not None
            and 0.25 <= abs(opt.delta) <= 0.35
            and opt.daysToExpiration is not None
            and 0 < opt.daysToExpiration <= self._max_dte
            and not opt.inTheMoney
        )

    @staticmethod
    def _ann_return(premium: float, collateral: float, dte: int) -> float:
        """Annualized return on collateral as a percentage."""
        if dte <= 0 or collateral <= 0:
            return 0.0
        return round((premium / collateral) * (365 / dte) * 100, 2)
