from pydantic import BaseModel
from enum import Enum
import orjson
from typing import TypeAlias, Union, Tuple, Self
from websockets import Data
from math import floor, ceil
from ib_async import Ticker, Stock, IB


"""
TODO:
    clean up the message actions
    create a better way to ack
    probably 4 buckets
    1. handshake ack
    2. state update ack
    3. server assertion ack
    4. closing connection ack
"""


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
    Buy = "BUY"
    Sell = "SELL"


class PubMessage(BaseModel):
    i: int


class TickerMessage(BaseModel):
    h: float
    l: float
    c: float
    o: float
    v: float

    @classmethod
    def from_ticker(cls, ticker: Ticker):
        return cls(
            h=ticker.high, l=ticker.low, c=ticker.close, o=ticker.open, v=ticker.volume
        )


class HandshakeStatus(str, Enum):
    Success = "Sucess"
    InvalidHandshake = "InvalidHandshake"
    SymbolInUse = "SymbolInUse"


class OrderAck(BaseModel):
    orderType: OrderType
    orderSize: Number


class ServerStateAssertion(BaseModel):
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


class SessionHandshake(BaseModel):
    """
    symbol: the stock symbol of the session
    publishCadence: the cadence at which to publish messages in seconds
    """

    symbol: str
    publishCadence: int


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

class TradingSession(BaseModel):
    symbol: str
    client: IB
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
    type_key = list(msg.keys())[0]
    try:
        msg_type = MessageParameter(type_key)
    except ValueError:
        raise KeyError(f"Invalid message type: {type_key}")

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
            data = SessionHandshake(**params)
        case MessageParameter.CloseConnection:
            data = CloseConnection(**params)
        case MessageParameter.ServerState:
            data = ServerState(**params)
    return (msg_type, data)
