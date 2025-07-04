from websockets import (
    serve,
    ServerConnection,
    ConnectionClosedError,
    ConnectionClosedOK,
)
from pydantic import ValidationError
from data_types import (
    MessageParameter,
    Subscribe,
    coerce_message_to_type,
    HandshakeAck,
    ServerStateAssertion,
    ServerState,
    HandshakeStatus,
    Handshake,
    OrderType,
)
from actions import pub_sub, place_order
from ib_async import IB, Stock
from typing import Optional, Union
import asyncio
import logging
from db import Database

state_db = Database()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("logger")

IBKR_IP_ADDRESS = ""
IBKR_PORT = 0

# TODO: add ping/pong logic
"""
TODO:
1. Upon successful handshake, an ib_async_client will be created
    a. get id from db
    b. connect async
    c. acknowledge to the client that a connection was successfully made
2. Wait for next message
3. On Sub, publish indefinitely
4. On pub interrupt, perform the associated action
"""


async def connection_handler(conn: ServerConnection):
    logger.info("accepted connection")
    ib_client: IB = IB()
    contract: Optional[Stock] = None

    try:
        # listen until a valid handshake message it passed by the client
        while True:
            msg = await conn.recv()
            try:
                t, hs = coerce_message_to_type(msg_str=msg)
            except ValidationError:
                await conn.send('"error": "Invalid Message"'.encode("utf-8"))
                continue
            if t == MessageParameter.HandShake:
                assert isinstance(hs, Handshake), "Message passed was not a handshake"
                symbol = hs.symbol
                contract = Stock(symbol)
                await state_db.insert(symbol)
                new_id = await state_db.new_id()
                await ib_client.connectAsync(
                    IBKR_IP_ADDRESS, IBKR_PORT, clientId=new_id
                )
                break
            else:
                # if the first message was not a handshake, then we acknowledge we recieved but indicate bad message
                await conn.send(
                    HandshakeAck(status=HandshakeStatus.FAILED)
                    .model_dump_json()
                    .encode("utf-8")
                )

        # acknowledge successful handshake
        await conn.send(
            HandshakeAck(status=HandshakeStatus.SUCCESS)
            .model_dump_json()
            .encode("utf-8")
        )

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
                    assert isinstance(stake_in, Union[float, int])
                    await state_db.buy(symbol, stake_in)
                    ack = await place_order(
                        ib_client=ib_client,
                        contract=contract,
                        order_type=OrderType.BUY,
                        order_value=stake_in,
                    )

                    await conn.send(ack.model_dump_json().encode("utf-8"))
                case MessageParameter.SubmitSellOrder:
                    stake_out = msg_data.sellOrder  # pyright: ignore
                    assert isinstance(stake_out, Union[float, int])
                    await state_db.sell(symbol, stake_out)
                    ack = await place_order(
                        ib_client=ib_client,
                        contract=contract,
                        order_type=OrderType.SELL,
                        order_value=stake_out,
                    )
                    await conn.send(ack.model_dump_json().encode("utf-8"))
                case MessageParameter.Subscribe:
                    assert isinstance(
                        msg_data, Subscribe
                    ), "Subscribe message is wrong type"
                    ticker = ib_client.reqMktData(contract, "", False, False)
                    msg = await pub_sub(
                        conn=conn,
                        sub_params=msg_data,
                        ibkr_ticker=ticker,
                    )
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
                    rx_msg = ServerStateAssertion(
                        symbol=msg_data.symbol, stake=stake
                    ).model_dump_json()
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
