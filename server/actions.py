from ib_async import (
    IB,
    Contract,
    LimitOrder,
    RealTimeBarList,
    LimitOrder,
    Trade,
)
from data_types import (
    ServerStateAssertionAck,
    ServerState,
    OrderType,
    TickerMessage,
    OrderAck,
    Number,
    MessageParameter,
    coerce_message_to_type,
    TradingSession,
    UpdateSubscription,
)
from db import Database
from time import time
import asyncio
from websockets import ServerConnection, Data
from typing import Union
import logging
from pydantic import ValidationError

logger = logging.getLogger("log")

ORDER_STATUS_POLL_CADENCE: float = 0.001  # Poll every millisecond


def create_order(
    action: OrderType, totalQuantity: float, lmtPrice: float
) -> LimitOrder:
    """
    Utility to create a LimitOrder.
    """
    return LimitOrder(
        action=action.value, totalQuantity=totalQuantity, lmtPrice=lmtPrice, tif="IOC"
    )


async def wait_for_trade(trade: Trade):
    """
    Utility to wait for the completion of a trade.
    """
    done = asyncio.Event()

    def is_done(_):
        if trade.isDone():
            done.set()

    trade.cancelledEvent += is_done
    trade.filledEvent += is_done

    if trade.isDone():
        return

    await done.wait()


def curry_bar_handler(queue: asyncio.Queue):
    """
    Define an event handler to update the queue of tickers.
    The event handlers only take synchronous functions.
    If there is a new ticker, pop it off the RealTimeBarList
    and push it on the queue.
    """
    def bar_handler(bars_list, new_bar):
        if new_bar and len(bars_list) > 0:
            bar = bars_list.pop()
            asyncio.create_task(queue.put(bar))

    return bar_handler


async def publish_messages(
    cadence: Number, conn: ServerConnection, ibkr_ticker: RealTimeBarList
) -> None:
    """
    Publish messages to the client indefinitely until these is an interrupt.
    Leverages a Ticker from IBKR to get the relevant messages.
    args:
        sub_params: Subscribe - subscription parameters
        conn: ServerConnection - the websocket connection object
    returns:
        None
    """

    queue = asyncio.Queue()
    handler = curry_bar_handler(queue)
    ibkr_ticker.updateEvent += handler
    logger.info(f"Publishing messages at cadence: {cadence}")
    while True:
        ticker = await queue.get()
        message = TickerMessage.from_ticker(ticker).model_dump_json().encode("utf-8")
        start = time()
        await conn.send(message)
        await asyncio.sleep(cadence - (time() - start))


async def place_order(
    ib_client: IB,
    contract: Contract,
    order_type: OrderType,
    order_value: Union[float, int],
) -> OrderAck:
    # TODO: figure out lmtPrice argument
    order = create_order(action=order_type, totalQuantity=order_value, lmtPrice=100.0)
    trade = ib_client.placeOrder(contract, order)

    await wait_for_trade(trade)

    filled = trade.filled()

    return OrderAck(
        orderType=order_type,
        filled=filled,
        remaining=order_value - filled,
        orderSize=order_value,
    )


async def pub_sub(
    conn: ServerConnection, cadence: Number, ibkr_ticker: RealTimeBarList
) -> Data:
    """
    Orchestrates publishing messages for the duration of the sub window.
    Allows for an interupt when a new message is recieved.
    args:
        conn: ServerConnection - the object holding the connection state
        sub_params: Subscribe - the parameters for the subscription
    returns:
        Tuple[bool, Optional[str]]
            bool - and indicator of whether or not the subscription was interupted
            str - the interupt message if the subscription was interupted
    """
    logger.info("Handling subscription")
    publish_task = asyncio.create_task(
        publish_messages(cadence=cadence, conn=conn, ibkr_ticker=ibkr_ticker)
    )
    interupt_task = asyncio.create_task(conn.recv())
    _, _ = await asyncio.wait(
        [publish_task, interupt_task], return_when=asyncio.FIRST_COMPLETED
    )

    # if the interupt task finishes, cancel the publish task
    # then grab the result from the coroutine to get the new message
    # otherwise cancel the interupt task
    publish_task.cancel()
    new_message = interupt_task.result()
    return new_message


async def service_client_action_request(
    session: TradingSession, msg: Data, conn: ServerConnection, state_db: Database
):
    """
    Performs some client request action on IBKR and ack back to the client.
    Updates session parameters when the client requests it.
    args:
        session: TradingSession - the object holding session attributes
        msg: Data - the message recieved from the client
        conn: ServerConnection - the object holding the websocket connnnection
        state_db Database - the in memory database
    """
    try:
        t, msg_data = coerce_message_to_type(msg_str=msg)
    except ValidationError:
        logger.info(f"message was invalid: {msg}")
        await conn.send('"error": "Invalid Message"'.encode("utf-8"))
        return
    except AssertionError:
        logger.info("msg is None when trying to read message type and data")
        return

    match t:
        case MessageParameter.SubmitBuyOrder:
            stake_in = msg_data.buyOrder  # pyright: ignore
            assert isinstance(stake_in, Union[float, int])
            ack = await place_order(
                ib_client=session.client,
                contract=session.contract,
                order_type=OrderType.Buy,
                order_value=stake_in,
            )

            # update state only with the amount of the order that was filled
            await state_db.buy(session.symbol, ack.filled)
            await conn.send(ack.model_dump_json().encode("utf-8"))
        case MessageParameter.SubmitSellOrder:
            stake_out = msg_data.sellOrder  # pyright: ignore
            assert isinstance(stake_out, Union[float, int])
            ack = await place_order(
                ib_client=session.client,
                contract=session.contract,
                order_type=OrderType.Sell,
                order_value=stake_out,
            )

            # update state only with the amount of the order that was filled
            await state_db.sell(session.symbol, ack.filled)
            await conn.send(ack.model_dump_json().encode("utf-8"))
        case MessageParameter.UpdateSubscription:
            # this will seldom be used in the beginning
            assert isinstance(
                msg_data, UpdateSubscription
            ), "Subscribe message is wrong type"
            session.update_sub_parameter(update=msg_data)
        case MessageParameter.CloseConnection:
            await conn.close()
            return
        case MessageParameter.ServerState:
            assert isinstance(msg_data, ServerState)
            session = await state_db.get(msg_data.symbol)  # pyright: ignore
            assert session is not None
            rx_msg = ServerStateAssertionAck(
                symbol=msg_data.symbol, stake=session.currentPosition
            ).model_dump_json()
            await conn.send(rx_msg)
