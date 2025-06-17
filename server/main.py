from websockets import (
    serve,
    ServerConnection,
    ConnectionClosedError,
    ConnectionClosedOK,
    Request
)
import asyncio
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("logger")


async def connection_entry(conn: ServerConnection):
    request = conn.request
    if request is None:
        await conn.close()
    logger.info(f"path: {request.path}") # pyright: ignore
    # route the connection based on the first message
    logger.info("Got entry connection")
    if request.path == "/base": # pyright: ignore
        await handle_connection_base(conn)
    elif request.path == "/other": # pyright: ignore
        await handle_connection_other(conn)


async def handle_connection_other(conn: ServerConnection):
    logger.info("serving connection to other")
    message = b"you are subscribed to other"
    try:
        echo = await conn.recv()
        await conn.send(f"Echo from other: {echo}")
        for _ in range(9):
            await asyncio.sleep(0.2)
            await conn.send(message)
    except ConnectionClosedOK:
        logger.info("client closed connection")
    except ConnectionClosedError:
        logger.info("closed connection")
    logger.info("exiting connection")



async def handle_connection_base(conn: ServerConnection):
    logger.info("serving connection to base")
    try:
        initial_message = json.loads(await conn.recv())
        logger.info(f"subscription params: {initial_message}")
        cadence = initial_message.get("publish_cadence")
        window_len = initial_message.get("window")
        iters = window_len // cadence
        for i in range(iters):
            await conn.send(json.dumps({"i": i}))
            await asyncio.sleep(cadence)

    except ConnectionClosedOK:
        logger.info("client closed connection")
    except ConnectionClosedError:
        logger.info("closed connection")
    logger.info("exiting connection")


async def main():
    async with serve(connection_entry, "localhost", 8080):
        logger.info("listening on ws://localhost:8080")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        logger.info("Starting")
        asyncio.run(main())
    except KeyboardInterrupt:
        pass



