from ib_async import (
    IB,
    Ticker,
    Contract,
    LimitOrder,
    RealTimeBarList,
    LimitOrder,
    Trade,
)
from pydantic import ValidationError
from data_types import OrderType, TickerMessage, OrderAck, Number
from time import time
import asyncio
from websockets import ServerConnection, Data
from typing import Union
import logging

logger = logging.getLogger("log")

ORDER_STATUS_POLL_CADENCE: float = 0.001  # Poll every millisecond


def create_order(
    action: OrderType, totalQuantity: float, lmtPrice: float
) -> LimitOrder:
    return LimitOrder(
        action=action.value, totalQuantity=totalQuantity, lmtPrice=lmtPrice, tif="IOC"
    )


async def wait_for_trade(trade: Trade):
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
    async def bar_handler(_, new_bar):
        await queue.put(new_bar)

    return bar_handler


async def publish_messages(
    cadence: Number, conn: ServerConnection, ibkr_ticker: RealTimeBarList
) -> None:
    """
    Publish messages to the client indefinitely until these is an interrupt
    Leverages a Ticker from IBKR to get the relevant messages
    args:
        sub_params: Subscribe - subscription parameters
        conn: ServerConnection - the websocket connection object
        TODO:
            ibkr_client: The IBKR client to request and publish messages
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
    order = create_order(action=order_type, totalQuantity=order_value, lmtPrice=100.0)
    # TODO: determine the error handling logic here
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
    Orchestrates publishing messages for the duration of the sub window
    Allows for an interupt when a new message is recieved
    args:
        conn: ServerConnection - the object holding the connection state
        sub_params: Subscribe - the parameters for the subscription
        TODO:
            the ibkr client will be passed here to actually grab the messages
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
    done, _ = await asyncio.wait(
        [publish_task, interupt_task], return_when=asyncio.FIRST_COMPLETED
    )

    # if the interupt task finishes, cancel the publish task
    # then grab the result from the coroutine to get the new message
    # otherwise cancel the interupt task
    publish_task.cancel()
    new_message = interupt_task.result()
    return new_message
