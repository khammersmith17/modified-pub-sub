from pydantic import BaseModel
from enum import Enum
import orjson
from typing import TypeAlias, Union, Tuple
from websockets import Data

class PubMessage(BaseModel):
    i: int

class ServerStateAssertion(BaseModel):
    symbol: str
    stake: float

class MessageParameter(str, Enum):
    SubmitBuyOrder = "submitBuyOrder"
    SubmitSellOrder = "submitSellOrder"
    Subscribe = "subscribe"
    HandShake = "handShake"
    CloseConnection = "closeConnection"
    ServerState = "serverState"


class ServerState(BaseModel):
    symbol: str

class SubmitBuyOrder(BaseModel):
    buyOrder: float


class SubmitSellOrder(BaseModel):
    sellOrder: float


class Subscribe(BaseModel):
    publishCadence: int
    window: int


class HandShake(BaseModel):
    symbol: str


class CloseConnection(BaseModel):
    status: str


ClientMessage: TypeAlias = Union[
    SubmitBuyOrder, SubmitSellOrder, Subscribe, HandShake, CloseConnection, ServerState
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
        case MessageParameter.Subscribe:
            data = Subscribe(**params)
        case MessageParameter.HandShake:
            data = HandShake(**params)
        case MessageParameter.CloseConnection:
            data = CloseConnection(**params)
        case MessageParameter.ServerState:
            data = ServerState(**params)
    return (msg_type, data)
