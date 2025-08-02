import math
from datetime import datetime, timedelta
from math import floor, ceil
from random import uniform as random_uniform
from typing import TypeAlias, Union, Tuple, Self, Optional
from enum import Enum
import orjson
from pydantic import BaseModel, ConfigDict
from websockets import Data
from ib_async import Stock, IB, RealTimeBar


class MessageSerializationError(Exception):
    pass


type Number = Union[int, float]


class StockPosition:
    __slots__ = ["_dollars", "_cents"]

    def __init__(self, dollars: int, cents: int):
        self._dollars = dollars
        self._cents = cents

    @classmethod
    def from_float(cls, value: float) -> Self:
        dollars: int = int(floor(value))
        cents: int = int(ceil((value - dollars) * 100))
        return cls(dollars=dollars, cents=cents)

    @classmethod
    def new(cls) -> Self:
        return cls(dollars=0, cents=0)

    def __add__(self, other: Self):
        self._check_type_on_arithmetic(other)
        new_cents = self._cents + other._cents
        rem = 0
        if new_cents >= 100:
            rem += 1
            new_cents = new_cents % 100
        new_dollars = self._dollars + other._dollars + rem
        return StockPosition(dollars=new_dollars, cents=new_cents)

    def __sub__(self, other: Self):
        self._check_type_on_arithmetic(other)
        cents_overflow = other._cents > self._cents
        if other._dollars > self._dollars or (
            self._dollars == other._dollars and cents_overflow
        ):
            raise ValueError("StockPosition value cannot go negative")
        if cents_overflow:
            self._dollars -= 1
            self._cents += 100

        new_cents = self._cents - other._cents
        new_dollars = self._dollars - other._dollars
        return StockPosition(dollars=new_dollars, cents=new_cents)

    def _check_type_on_arithmetic(self, other):
        if not isinstance(other, Self):
            raise ValueError(
                "Cannot add a non StockPosition instance to a StockPosition instance"
            )


class OrderType(str, Enum):
    Buy = "Buy"
    Sell = "Sell"


class SimulatedOrder(BaseModel):
    order_type: OrderType
    order_size: float


class SimulatedTrade(BaseModel):
    amt_filled: float
    amt_remaining: float

    def filled(self) -> float:
        return self.amt_filled


class PubMessage(BaseModel):
    i: int


class SimulatedBar(BaseModel):
    high: float
    low: float
    close: float
    open_: float
    volume: float
    time: datetime

    def perturb(self):
        self.high *= random_uniform(0.95, 0.99)
        self.low *= random_uniform(0.95, 0.99)
        self.close *= random_uniform(0.95, 0.99)
        self.open_ *= random_uniform(0.95, 0.99)
        self.volume *= random_uniform(0.95, 0.99)
        self.time += timedelta(seconds=5)


class TickerMessage(BaseModel):
    h: float
    l: float
    c: float
    o: float
    v: float
    timestamp: int

    @classmethod
    def from_ticker(cls, ticker: Union[RealTimeBar, SimulatedBar]):
        return cls(
            h=ticker.high,
            l=ticker.low,
            c=ticker.close,
            o=ticker.open_,
            v=ticker.volume,
            timestamp=int(math.floor(ticker.time.timestamp())),
        )


class TickerPayload(BaseModel):
    ticker: Optional[TickerMessage]


class HandshakeStatus(str, Enum):
    Success = "Sucess"
    InvalidHandshake = "InvalidHandshake"
    SymbolInUse = "SymbolInUse"


class OrderAck(BaseModel):
    orderType: OrderType
    filled: Number
    remaining: Number
    orderSize: Number


class ServerStateAssertionAck(BaseModel):
    symbol: str
    stake: float


class MessageParameter(str, Enum):
    SubmitBuyOrder = "submitBuyOrder"
    SubmitSellOrder = "submitSellOrder"
    UpdateSubscription = "updateSubscription"
    SessionHandshake = "sessionHandshake"
    RecoveryHandshake = "recoveryHandshake"
    CloseConnection = "closeConnection"
    ServerState = "serverState"


class ServerState(BaseModel):
    symbol: str


class SubmitBuyOrder(BaseModel):
    buyOrder: Number


class SubmitSellOrder(BaseModel):
    sellOrder: Number


class UpdateSubscription(BaseModel):
    publishCadence: int


class PositionType(str, Enum):
    Long = "Long"
    Short = "Short"


class SessionHandshake(BaseModel):
    """
    symbol: the stock symbol of the session
    publishCadence: the cadence at which to publish messages in seconds
    """

    model_config = ConfigDict(use_enum_values=True, extra="ignore")
    symbol: str
    publishCadence: int
    positionType: PositionType


class RecoveryHandshake(BaseModel):
    symbol: str


class HandshakeAck(BaseModel):
    status: HandshakeStatus

    @classmethod
    def construct_handshake_error(
        cls, hs: Union[SessionHandshake, RecoveryHandshake]
    ) -> bytes:
        if isinstance(hs, SessionHandshake):
            return (
                cls(status=HandshakeStatus.SymbolInUse)
                .model_dump_json()
                .encode("utf-8")
            )
        else:
            return (
                cls(status=HandshakeStatus.InvalidHandshake)
                .model_dump_json()
                .encode("utf-8")
            )


class CloseConnection(BaseModel):
    status: str


class SimulatedClient:
    def __init__(self, id: int):
        self.id = id


class TradingSession(BaseModel):
    model_config = ConfigDict(use_enum_values=True, extra="ignore")
    symbol: str
    client: IB
    positionType: PositionType
    contract: Stock
    publishCadence: int
    currentPosition: Number

    def update_sub_parameter(self, update: UpdateSubscription) -> None:
        self.publishCadence = update.publishCadence


ClientMessage: TypeAlias = Union[
    SubmitBuyOrder,
    SubmitSellOrder,
    UpdateSubscription,
    SessionHandshake,
    CloseConnection,
    ServerState,
    RecoveryHandshake,
]


def coerce_message_to_type(msg_str: Data) -> Tuple[MessageParameter, ClientMessage]:
    try:
        msg = orjson.loads(msg_str)
    except orjson.JSONDecodeError:
        raise ValueError(f"Invalid Json Error: {msg_str}")
    try:
        type_key = list(msg.keys())[0]
        msg_type = MessageParameter(type_key)
    except (ValueError, IndexError):
        raise MessageSerializationError("Invalid message")

    params = msg.get(type_key)
    data = None
    match msg_type:
        case MessageParameter.SubmitBuyOrder:
            data = SubmitBuyOrder(**params)
        case MessageParameter.SubmitSellOrder:
            data = SubmitSellOrder(**params)
        case MessageParameter.UpdateSubscription:
            data = UpdateSubscription(**params)
        case MessageParameter.SessionHandshake:
            data = SessionHandshake(**params)
        case MessageParameter.RecoveryHandshake:
            data = RecoveryHandshake(**params)
        case MessageParameter.CloseConnection:
            data = CloseConnection(**params)
        case MessageParameter.ServerState:
            data = ServerState(**params)
    return (msg_type, data)
