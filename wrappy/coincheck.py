import asyncio
import pybotters
from traceback import format_exc
from .base import BotBase
from .exceptions import APIException


class CoinCheck(BotBase):
    def __init__(self, config: str, symbol: str):
        super().__init__(config)
        self.symbol = symbol


    async def _requests(self, method: str, url: str, params=None, data=None):
        async with pybotters.Client(apis=None, base_url="https://coincheck.com") as client:
            response = await client.request(method, url=url, params=params, data=data)
            if not str(response.status).startswith('2'):
                if str(response.status).startswith("429"):
                    self.log_error("429 Too Many Requests")
                    await asyncio.sleep(1)
                await self.statusNotify(f"{response.status} error")
                raise APIException(response)
            return await response.json()


    async def fetch_ticker(self):
        for failed_count in range(1, 6):
            try:
                return await self._requests("GET", url="/api/ticker", params={"pair": self.symbol})
            except Exception as e:
                if failed_count >= 5:
                    self.log_error("API request failed in fetch ticker")
                    self.log_error(format_exc())
                    raise e
                await asyncio.sleep(1)
