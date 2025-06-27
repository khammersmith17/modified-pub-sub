from websockets import (
    serve,
    ServerConnection,
    ConnectionClosedError,
    ConnectionClosedOK,
    Data,
)
from pydantic import ValidationError
from data_types import MessageParameter, Subscribe, coerce_message_to_type, PubMessage, ServerStateAssertion, ServerState
from typing import Tuple, Optional
import asyncio
import logging
from db import Database
from time import time

state_db = Database()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("logger")


async def publish_messages(sub_params: Subscribe, conn: ServerConnection) -> None:
    """
    Publish messages to the client
    args:
        sub_params: Subscribe - subscription parameters
        conn: ServerConnection - the websocket connection object
        TODO:
            ibkr_client: The IBKR client to request and publish messages
    returns:
        None
    """
    num_messages = sub_params.window // sub_params.publishCadence
    logger.info(f"num_messages: {num_messages}")
    for i in range(num_messages):
        # get the tickers
        logger.info("publishing single message")
        message = PubMessage(i=i).model_dump_json()
        start = time()
        await conn.send(message)
        await asyncio.sleep(sub_params.publishCadence - (time() - start))
    return


async def pub_sub(
    conn: ServerConnection, sub_params: Subscribe
) -> Tuple[bool, Optional[Data]]:
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
        publish_messages(sub_params=sub_params, conn=conn)
    )
    interupt_task = asyncio.create_task(conn.recv())
    done, _ = await asyncio.wait(
        [publish_task, interupt_task], return_when=asyncio.FIRST_COMPLETED
    )

    # if the interupt task finishes, cancel the publish task
    # then grab the result from the coroutine to get the new message
    # otherwise cancel the interupt task
    if interupt_task in done:
        logger.info("interupt triggered, canceling the publish task")
        publish_task.cancel()
        new_message = interupt_task.result()
        return (True, new_message)
    else:
        interupt_task.cancel()
        logger.info("canceled the interupt task")
        return (False, None)


async def connection_handler(conn: ServerConnection):
    logger.info("accepted connection")
    try:
        while True:
            # wait until the client sends a valid handshake
            msg = await conn.recv()
            try:
                t, hs = coerce_message_to_type(msg_str=msg)
            except ValidationError:
                await conn.send('"error": "Invalid Message"'.encode("utf-8"))
                continue
            if t == MessageParameter.HandShake:
                symbol = hs.symbol  # pyright: ignore
                await state_db.insert(symbol)
                break
            else:
                await conn.send('"error": "Invalid HandShake"')

        logger.info(f"aquired handshake: {symbol}")

        msg = await conn.recv()
        logger.info(f"first message after handshake: {msg}")
        while True:
            try:
                assert msg is not None
                t, msg_data = coerce_message_to_type(msg_str=msg)
            except ValidationError:
                logger.info(f"message was invalid: {msg}")
                await conn.send('"error": "Invalid Message"'.encode("utf-8"))
                continue
            except AssertionError:
                logger.info("msg is None when trying to read message type and data")
                continue

            logger.info(f"t:\n{t}\nmsg_data:{msg_data}")
            match t:
                case MessageParameter.SubmitBuyOrder:
                    stake_in = msg_data.buyOrder  # pyright: ignore
                    await state_db.buy(symbol, stake_in)
                    # TODO: submit buy order on IBKR here
                case MessageParameter.SubmitSellOrder:
                    stake_out = msg_data.sellOrder  # pyright: ignore
                    await state_db.sell(symbol, stake_out)
                    # TODO: submit sell order on IBKR here
                case MessageParameter.Subscribe:
                    interupted, msg = await pub_sub(
                        conn=conn, sub_params=msg_data # pyright: ignore
                    )  
                    if interupted:
                        # breaking this step to process the interupt message
                        continue
                case MessageParameter.CloseConnection:
                    await conn.close()
                    return
                case MessageParameter.HandShake:
                    pass
                case MessageParameter.ServerState:
                    assert isinstance(msg_data, ServerState)
                    stake = await state_db.get(msg_data.symbol) 
                    assert stake is not None
                    rx_msg = ServerStateAssertion(symbol=msg_data.symbol, stake=stake).model_dump_json() 
                    await conn.send(rx_msg)

            msg = await conn.recv()
    except ConnectionClosedOK:
        logger.info("client closed connection")
    except ConnectionClosedError:
        logger.info("closed connection")
    logger.info("exiting connection")


async def main():
    async with serve(connection_handler, "localhost", 8080):
        logger.info("listening on ws://localhost:8080")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        logger.info("Starting")
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
