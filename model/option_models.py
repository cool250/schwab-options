from typing import Optional, Dict, List
from pydantic import BaseModel, root_validator

class OptionDeliverable(BaseModel):
    symbol: str
    assetType: str
    deliverableUnits: float
    currencyType: Optional[str]

class OptionDetail(BaseModel):
    putCall: str
    symbol: str
    description: str
    exchangeName: str
    bid: float
    ask: float
    last: float
    mark: float
    bidSize: int
    askSize: int
    bidAskSize: str
    lastSize: int
    highPrice: float
    lowPrice: float
    openPrice: float
    closePrice: float
    totalVolume: int
    tradeTimeInLong: int
    quoteTimeInLong: int
    netChange: float
    volatility: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    openInterest: int
    timeValue: float
    theoreticalOptionValue: float
    theoreticalVolatility: float
    optionDeliverablesList: Optional[List[OptionDeliverable]]
    strikePrice: float
    expirationDate: str
    daysToExpiration: int
    expirationType: str
    lastTradingDay: int
    multiplier: float
    settlementType: str
    deliverableNote: str
    percentChange: float
    markChange: float
    markPercentChange: float
    intrinsicValue: float
    extrinsicValue: float
    optionRoot: str
    exerciseType: str
    high52Week: float
    low52Week: float
    nonStandard: bool
    inTheMoney: bool
    mini: bool
    pennyPilot: bool

class OptionChainResponse(BaseModel):
    symbol: str
    status: str
    underlying: Optional[Dict[str, float]]
    strategy: str
    interval: float
    isDelayed: bool
    isIndex: bool
    interestRate: float
    underlyingPrice: float
    volatility: float
    daysToExpiration: float
    dividendYield: Optional[float]
    numberOfContracts: int
    assetMainType: str
    assetSubType: str
    isChainTruncated: bool
    callExpDateMap: Optional[Dict[str, Dict[str, List[OptionDetail]]]]
    putExpDateMap: Optional[Dict[str, Dict[str, List[OptionDetail]]]]

    @root_validator(pre=True)
    def transform_exp_date_maps(cls, values):
        for map_key in ["callExpDateMap", "putExpDateMap"]:
            exp_date_map = values.get(map_key)
            if exp_date_map:
                transformed_map = {}
                for exp_date, strikes in exp_date_map.items():
                    transformed_map[exp_date] = {
                        strike: [OptionDetail(**detail) for detail in details]
                        for strike, details in strikes.items()
                    }
                values[map_key] = transformed_map
        return values