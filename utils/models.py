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


class AccountHash(BaseModel):
    hashValue: str