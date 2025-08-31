from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class Instrument(BaseModel):
    cusip: Optional[str] = None
    symbol: Optional[str] = None
    description: Optional[str] = None
    instrumentId: Optional[int] = None
    netChange: Optional[float] = None
    type: Optional[str] = None
    assetType: Optional[str] = None
    closingPrice: Optional[float] = None


class TransferItem(BaseModel):
    instrument: Optional[Instrument] = None
    amount: Optional[float] = None
    cost: Optional[float] = None
    price: Optional[float] = None
    feeType: Optional[str] = None
    positionEffect: Optional[str] = None


class User(BaseModel):
    cdDomainId: Optional[str] = None
    login: Optional[str] = None
    type: Optional[str] = None
    userId: Optional[int] = None
    systemUserName: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    brokerRepCode: Optional[str] = None


class Activity(BaseModel):
    activityId: Optional[int] = None
    time: Optional[datetime] = None
    user: Optional[User] = None
    description: Optional[str] = None
    accountNumber: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    subAccount: Optional[str] = None
    tradeDate: Optional[datetime] = None
    settlementDate: Optional[datetime] = None
    positionId: Optional[int] = None
    orderId: Optional[int] = None
    netAmount: Optional[float] = None
    activityType: Optional[str] = None
    transferItems: Optional[List[TransferItem]] = None


class Position(BaseModel):
    shortQuantity: Optional[float] = None
    averagePrice: Optional[float] = None
    currentDayProfitLoss: Optional[float] = None
    currentDayProfitLossPercentage: Optional[float] = None
    longQuantity: Optional[float] = None
    settledLongQuantity: Optional[float] = None
    settledShortQuantity: Optional[float] = None
    agedQuantity: Optional[float] = None
    instrument: Optional[Instrument] = None
    marketValue: Optional[float] = None
    maintenanceRequirement: Optional[float] = None
    averageLongPrice: Optional[float] = None
    averageShortPrice: Optional[float] = None
    taxLotAverageLongPrice: Optional[float] = None
    taxLotAverageShortPrice: Optional[float] = None
    longOpenProfitLoss: Optional[float] = None
    shortOpenProfitLoss: Optional[float] = None
    previousSessionLongQuantity: Optional[float] = None
    previousSessionShortQuantity: Optional[float] = None
    currentDayCost: Optional[float] = None


class InitialBalances(BaseModel):
    accruedInterest: Optional[float] = None
    availableFundsNonMarginableTrade: Optional[float] = None
    bondValue: Optional[float] = None
    buyingPower: Optional[float] = None
    cashBalance: Optional[float] = None
    cashAvailableForTrading: Optional[float] = None
    cashReceipts: Optional[float] = None
    dayTradingBuyingPower: Optional[float] = None
    dayTradingBuyingPowerCall: Optional[float] = None
    dayTradingEquityCall: Optional[float] = None
    equity: Optional[float] = None
    equityPercentage: Optional[float] = None
    liquidationValue: Optional[float] = None
    longMarginValue: Optional[float] = None
    longOptionMarketValue: Optional[float] = None
    longStockValue: Optional[float] = None
    maintenanceCall: Optional[float] = None
    maintenanceRequirement: Optional[float] = None
    margin: Optional[float] = None
    marginEquity: Optional[float] = None
    moneyMarketFund: Optional[float] = None
    mutualFundValue: Optional[float] = None
    regTCall: Optional[float] = None
    shortMarginValue: Optional[float] = None
    shortOptionMarketValue: Optional[float] = None
    shortStockValue: Optional[float] = None
    totalCash: Optional[float] = None
    isInCall: Optional[bool] = None
    unsettledCash: Optional[float] = None
    pendingDeposits: Optional[float] = None
    marginBalance: Optional[float] = None
    shortBalance: Optional[float] = None
    accountValue: Optional[float] = None


class CurrentBalances(BaseModel):
    availableFunds: Optional[float] = None
    availableFundsNonMarginableTrade: Optional[float] = None
    buyingPower: Optional[float] = None
    buyingPowerNonMarginableTrade: Optional[float] = None
    dayTradingBuyingPower: Optional[float] = None
    dayTradingBuyingPowerCall: Optional[float] = None
    equity: Optional[float] = None
    equityPercentage: Optional[float] = None
    longMarginValue: Optional[float] = None
    maintenanceCall: Optional[float] = None
    maintenanceRequirement: Optional[float] = None
    marginBalance: Optional[float] = None
    regTCall: Optional[float] = None
    shortBalance: Optional[float] = None
    shortMarginValue: Optional[float] = None
    sma: Optional[float] = None
    isInCall: Optional[bool] = None
    stockBuyingPower: Optional[float] = None
    optionBuyingPower: Optional[float] = None


class ProjectedBalances(BaseModel):
    availableFunds: Optional[float] = None
    availableFundsNonMarginableTrade: Optional[float] = None
    buyingPower: Optional[float] = None
    buyingPowerNonMarginableTrade: Optional[float] = None
    dayTradingBuyingPower: Optional[float] = None
    dayTradingBuyingPowerCall: Optional[float] = None
    equity: Optional[float] = None
    equityPercentage: Optional[float] = None
    longMarginValue: Optional[float] = None
    maintenanceCall: Optional[float] = None
    maintenanceRequirement: Optional[float] = None
    marginBalance: Optional[float] = None
    regTCall: Optional[float] = None
    shortBalance: Optional[float] = None
    shortMarginValue: Optional[float] = None
    sma: Optional[float] = None
    isInCall: Optional[bool] = None
    stockBuyingPower: Optional[float] = None
    optionBuyingPower: Optional[float] = None


class SecuritiesAccount(BaseModel):
    accountNumber: Optional[str] = None
    roundTrips: Optional[int] = None
    isDayTrader: Optional[bool] = None
    isClosingOnlyRestricted: Optional[bool] = None
    pfcbFlag: Optional[bool] = None
    positions: Optional[List[Position]] = None
    initialBalances: Optional[InitialBalances] = None
    currentBalances: Optional[CurrentBalances] = None
    projectedBalances: Optional[ProjectedBalances] = None

class AccountHash(BaseModel):
    hashValue: str