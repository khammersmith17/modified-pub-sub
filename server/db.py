import asyncio
from typing import Optional
from typing import Dict
from data_types import TradingSession


class Database:
    def __init__(self):
        self._map: Dict[str, TradingSession] = dict()
        self.next_id = 0
        self._id_lock = asyncio.Lock()
        self._map_lock = asyncio.Lock()

    async def new_id(self) -> int:
        async with self._id_lock:
            i = self.next_id
            self.next_id += 1
        return i

    async def get(self, symbol: str) -> Optional[TradingSession]:
        async with self._map_lock:
            key_value = self._map.get(symbol)
            if key_value is None:
                raise KeyError(f"symbol: {symbol} not in db")
            return key_value

    async def buy(self, symbol: str, buyOrder: float) -> None:
        async with self._map_lock:
            key_value = self._map.get(symbol)
            if key_value is None:
                raise KeyError(f"symbol: {symbol} not in the database")
            key_value.currentPosition += buyOrder

    async def sell(self, symbol: str, sellOrder: float) -> None:
        async with self._map_lock:
            key_value = self._map.get(symbol)
            if key_value is None:
                raise KeyError(f"symbol: {symbol} not in the database")
            key_value.currentPosition = max(key_value.currentPosition - sellOrder, 0)

    async def delete(self, symbol: str) -> None:
        async with self._map_lock:
            self._map.pop(symbol, None)

    async def insert(self, symbol: str, session: TradingSession) -> bool:
        """
        Insert a new symbol
        args:
            symbol: str - the name of the symbol for the session
        returns:
            bool - indication of success
                - variants of failure
                    - this symbol already is being used in another session
        """
        async with self._map_lock:
            is_active = self._map.get(symbol)
            if is_active is not None:
                return False
            self._map.update({symbol: session})
            return True

    def __repr__(self) -> str:
        return f"current data: {self._map}"
