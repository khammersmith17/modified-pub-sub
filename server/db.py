import asyncio
from typing import Optional
from typing import Dict


class Database:
    def __init__(self):
        self._map: Dict[str, float] = dict()
        self._lock = asyncio.Lock()

    async def set(self, symbol: str, value: float) -> None:
        async with self._lock:
            self._map.update({symbol: value})

    async def get(self, symbol: str) -> Optional[float]:
        async with self._lock:
            key_value = self._map.get(symbol)
            if key_value is None:
                raise KeyError(f"symbol: {symbol} not in db")
            return key_value

    async def buy(self, symbol: str, buyOrder: float) -> None:
        async with self._lock:
            key_value = self._map.get(symbol)
            if key_value is None:
                raise KeyError(f"symbol: {symbol} not in the database")
            self._map.update({symbol: key_value + buyOrder})

    async def sell(self, symbol: str, sellOrder: float) -> None:
        async with self._lock:
            key_value = self._map.get(symbol)
            if key_value is None:
                raise KeyError(f"symbol: {symbol} not in the database")
            self._map.update({symbol: key_value - sellOrder})

    async def delete(self, symbol: str) -> None:
        async with self._lock:
            self._map.pop(symbol, None)

    async def insert(self, symbol: str) -> None:
        async with self._lock:
            self._map.update({symbol: 0.0})

    def __repr__(self) -> str:
        return f"current data: {self._map}"
