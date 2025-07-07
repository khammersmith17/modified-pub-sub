from websockets import (
    serve,
    ServerConnection,
    ConnectionClosedError,
    ConnectionClosedOK,
)
from pydantic import ValidationError
from data_types import (
    TradingSession,
    MessageParameter,
    UpdateSubscription,
    coerce_message_to_type,
    HandshakeAck,
    ServerStateAssertion,
    ServerState,
    HandshakeStatus,
    SessionHandshake,
    RecoveryHandshake,
    OrderType,
)
from actions import pub_sub, place_order
from ib_async import IB, Stock
from typing import Optional, Union, Tuple
import asyncio
import logging
from db import Database

state_db = Database()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("logger")

IBKR_IP_ADDRESS = ""
IBKR_PORT = 0


# TODO: then write a simulated counterpart to test on


async def perform_handshake(
    conn: ServerConnection,
) -> Tuple[bool, Optional[TradingSession]]:
    """
    Perform the handshake with the client
    If the session is new, then create ib client, contract with the symbol, and write an entry into the state database
    If the session is a renewal of a session where the connection was dropped, then retrieve the session information
    Session state will be returned to the main loop
    args:
        conn: ServerConnection - the websocket connection object
    returns:
        Tuple[bool, Optional[TradingSession]]: bool indicates success, on the success case the TradingSession will be non null, in the case of failure it will be null
    """
    try:
        while True:
            msg = await conn.recv()
            try:
                t, hs = coerce_message_to_type(msg_str=msg)
            except ValidationError:
                await conn.send('"error": "Invalid Message"'.encode("utf-8"))
                continue
            if (
                t != MessageParameter.SessionHandshake
                or t != MessageParameter.RecoveryHandshake
            ):
                # if the first message was not a handshake, then we acknowledge we recieved but indicate bad message
                await conn.send(
                    HandshakeAck(status=HandshakeStatus.InvalidHandshake)
                    .model_dump_json()
                    .encode("utf-8")
                )
                continue
            assert isinstance(
                hs, Union[SessionHandshake, RecoveryHandshake]
            ), "Message passed was not a handshake"
            symbol = hs.symbol
            if isinstance(hs, SessionHandshake):
                contract = Stock(symbol)
                ib_client = IB()
                new_id = await state_db.new_id()
                await ib_client.connectAsync(
                    IBKR_IP_ADDRESS, IBKR_PORT, clientId=new_id
                )
                session = TradingSession(
                    symbol=symbol,
                    client=ib_client,
                    publishCadence=hs.publishCadence,
                    contract=contract,
                    currentPosition=0.0,
                )
                success = await state_db.insert(symbol, session)
            else:
                session = await state_db.get(symbol)
                success = True if session is not None else False
            if not success:
                # if new session there is another active session
                # or a renewed session was not found
                await conn.send(HandshakeAck.construct_handshake_error(hs))
                continue
            break

        # acknowledge successful handshake
        await conn.send(
            HandshakeAck(status=HandshakeStatus.Success)
            .model_dump_json()
            .encode("utf-8")
        )
        return True, session
    except ConnectionClosedOK:
        logger.info("client closed connection")
        return False, None
    except ConnectionClosedError:
        logger.info("closed connection")
        return False, None


async def connection_handler(conn: ServerConnection):
    """
    The main session loop
    Handshake will be performed
    Messages will be published until some action is requested from the client
    When a publish window is interrupted, the action will be handled and acked
    args:
        conn: ServerConnection - the websocket connection object
    """
    logger.info("accepted connection")

    try:
        success, session = await perform_handshake(conn)
        if not success:
            logger.info("Unable to agree on session with client")
            return

        assert session is not None, "Null session returned from successful handshake"
        logger.info(f"aquired handshake: {session.symbol}")

        while True:
            ticker = session.client.reqMktData(
                session.contract, "", False, False
            )
            msg = await pub_sub(
                conn=conn,
                cadence=session.publishCadence,
                ibkr_ticker=ticker,
            )

            try:
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
                    await state_db.buy(session.symbol, stake_in)
                    ack = await place_order(
                        ib_client=session.client,
                        contract=session.contract,
                        order_type=OrderType.Buy,
                        order_value=stake_in,
                    )
                    await conn.send(ack.model_dump_json().encode("utf-8"))
                case MessageParameter.SubmitSellOrder:
                    stake_out = msg_data.sellOrder  # pyright: ignore
                    assert isinstance(stake_out, Union[float, int])
                    await state_db.sell(session.symbol, stake_out)
                    ack = await place_order(
                        ib_client=session.client,
                        contract=session.contract,
                        order_type=OrderType.Sell,
                        order_value=stake_out,
                    )
                    await conn.send(ack.model_dump_json().encode("utf-8"))
                case MessageParameter.UpdateSubscription:
                    assert isinstance(
                        msg_data, UpdateSubscription
                    ), "Subscribe message is wrong type"
                    session.update_sub_parameter(update=msg_data)
                case MessageParameter.CloseConnection:
                    await conn.close()
                    return
                case MessageParameter.ServerState:
                    assert isinstance(msg_data, ServerState)
                    session = await state_db.get(msg_data.symbol)
                    assert session is not None
                    rx_msg = ServerStateAssertion(
                        symbol=msg_data.symbol, stake=session.currentPosition
                    ).model_dump_json()
                    await conn.send(rx_msg)
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
