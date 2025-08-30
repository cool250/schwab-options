from pydantic import BaseModel
from typing import Optional, List


class Instrument(BaseModel):
    assetType: str
    symbol: str
    description: str
    amount: Optional[float] = None
    cost: Optional[float] = None
    feeType: Optional[str] = None


class TransferItem(BaseModel):
    instrument: Instrument  # Made the entire instrument optional


class Transaction(BaseModel):
    activityId: int
    time: str
    accountNumber: str
    type: str
    netAmount: float
    transferItems: List[TransferItem]

class InitialBalances(BaseModel):
    accruedInterest: float
    availableFundsNonMarginableTrade: float
    bondValue: float
    buyingPower: float
    cashBalance: float
    cashAvailableForTrading: float
    cashReceipts: float
    dayTradingBuyingPower: float
    dayTradingBuyingPowerCall: float
    dayTradingEquityCall: float
    equity: float
    equityPercentage: float
    liquidationValue: float
    longMarginValue: float
    longOptionMarketValue: float
    longStockValue: float
    maintenanceCall: float
    maintenanceRequirement: float
    margin: float
    marginEquity: float
    moneyMarketFund: float
    mutualFundValue: float
    regTCall: float
    shortMarginValue: float
    shortOptionMarketValue: float
    shortStockValue: float
    totalCash: float
    isInCall: bool
    pendingDeposits: float
    marginBalance: float
    shortBalance: float
    accountValue: float


class CurrentBalances(BaseModel):
    accruedInterest: float
    cashBalance: float
    cashReceipts: float
    longOptionMarketValue: float
    liquidationValue: float
    longMarketValue: float
    moneyMarketFund: float
    savings: float
    shortMarketValue: float
    pendingDeposits: float
    mutualFundValue: float
    bondValue: float
    shortOptionMarketValue: float
    availableFunds: float
    availableFundsNonMarginableTrade: float
    buyingPower: float
    buyingPowerNonMarginableTrade: float
    dayTradingBuyingPower: float
    equity: float
    equityPercentage: float
    longMarginValue: float
    maintenanceCall: float
    maintenanceRequirement: float
    marginBalance: float
    regTCall: float
    shortBalance: float
    shortMarginValue: float
    sma: float


class ProjectedBalances(BaseModel):
    availableFunds: float
    availableFundsNonMarginableTrade: float
    buyingPower: float
    dayTradingBuyingPower: float
    dayTradingBuyingPowerCall: float
    maintenanceCall: float
    regTCall: float
    isInCall: bool
    stockBuyingPower: float


class AggregatedBalance(BaseModel):
    currentLiquidationValue: float
    liquidationValue: float


class SecuritiesAccount(BaseModel):
    type: str
    accountNumber: str
    roundTrips: int
    isDayTrader: bool
    isClosingOnlyRestricted: bool
    pfcbFlag: bool
    initialBalances: InitialBalances
    currentBalances: CurrentBalances
    projectedBalances: ProjectedBalances
    aggregatedBalance: Optional[AggregatedBalance] = None  # Made optional

class AccountHash(BaseModel):
    hashValue: str