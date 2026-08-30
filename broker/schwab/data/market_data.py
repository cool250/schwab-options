from pydantic import BaseModel, RootModel
from typing import List, Optional

class Fundamental(BaseModel):
    avg10DaysVolume: Optional[float] = None
    avg1YearVolume: Optional[float] = None
    divAmount: Optional[float] = None
    divFreq: Optional[int] = None
    divPayAmount: Optional[float] = None
    divYield: Optional[float] = None
    eps: Optional[float] = None
    fundLeverageFactor: Optional[float] = None
    lastEarningsDate: Optional[str] = None
    peRatio: Optional[float] = None
    declarationDate: Optional[str] = None  # Made optional
    divExDate: Optional[str] = None  # Made optional
    divPayDate: Optional[str] = None  # Made optional
    nextDivExDate: Optional[str] = None  # Made optional
    nextDivPayDate: Optional[str] = None  # Made optional

class Quote(BaseModel):
    _52WeekHigh: Optional[float] = None
    _52WeekLow: Optional[float] = None
    askMICId: Optional[str] = None
    askPrice: Optional[float] = None
    askSize: Optional[int] = None
    askTime: Optional[int] = None
    bidMICId: Optional[str] = None
    bidPrice: Optional[float] = None
    bidSize: Optional[int] = None
    bidTime: Optional[int] = None
    closePrice: Optional[float] = None
    highPrice: Optional[float] = None
    lastMICId: Optional[str] = None
    lastPrice: Optional[float] = None
    lastSize: Optional[int] = None
    lowPrice: Optional[float] = None
    mark: Optional[float] = None
    markChange: Optional[float] = None
    markPercentChange: Optional[float] = None
    netChange: Optional[float] = None
    netPercentChange: Optional[float] = None
    openPrice: Optional[float] = None
    postMarketChange: Optional[float] = None
    postMarketPercentChange: Optional[float] = None
    quoteTime: Optional[int] = None
    securityStatus: Optional[str] = None
    totalVolume: Optional[int] = None
    tradeTime: Optional[int] = None

class Asset(BaseModel):
    assetMainType: str
    assetSubType: Optional[str] = None  # Made optional
    quoteType: Optional[str] = None  # Made optional
    realtime: bool
    ssid: int
    symbol: str
    fundamental: Optional[Fundamental] = None  # Made optional
    quote: Optional[Quote] = None

class StockQuotes(RootModel):
    root: dict[str, Asset]

class Candle(BaseModel):
    open: float
    high: float
    low: float
    close: float
    volume: int
    datetime: int
    
    def get_datetime(self):
        """Convert epoch milliseconds to datetime object"""
        from datetime import datetime
        # Check if datetime is in milliseconds (13 digits) or seconds (10 digits)
        if len(str(self.datetime)) >= 13:
            # Convert from milliseconds
            return datetime.fromtimestamp(self.datetime / 1000)
        else:
            # Convert from seconds
            return datetime.fromtimestamp(self.datetime)

class PriceHistoryResponse(BaseModel):
    symbol: str
    candles: List[Candle]
