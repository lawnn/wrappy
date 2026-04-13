import asyncio
import pybotters
from typing import Literal, Union
from decimal import Decimal
from .time_util import now_jst
from .base import BotBase
from .exceptions import RequestException


class bitflyer(BotBase):
    def __init__(self, config: str, symbol: str):
        super().__init__(config)
        # 通貨ペア
        self.symbol = symbol
        # APIを呼ぶ回数
        self.api_call_count_from_private = 0    #5分間で500回まで
        self.api_call_count_from_order = 0      #5分間で300回まで
        # API keyの設定
        self.key = {"bitflyer": self.config["bitflyer"]}
        # 何かしらのエラーがでたときに繰り返す回数
        self.retry_count = 3

        # position
        self.position = {}
        # 発注ID
        self.order_acceptanceID = []

    async def stop(self):
        """
        ボットを停止します.
        """
        self.log_debug("bitflyer stop start")
        super().stop()
        await self._cancel_and_liquidate()
        self.log_debug("bitflyer stop end")


    async def _cancel_and_liquidate(self, moq = 0.01):
        """
        全ての注文をキャンセルした後、ポジションを成行で反対売買してクローズします.
        :param moq(Minimum Order Quantity)　最小ロットです
        """
        self.log_debug("_cancel_and_liquidate start.")
        self.log_info("Canceling all open orders.")
        # 全てキャンセル.
        await self.cancel_all_orders()
        await asyncio.sleep(5)
        # 5秒置いてさらに全てキャンセル.
        await self.cancel_all_orders()
        await asyncio.sleep(5)
        position = await self.fetch_my_position()
        if position:
            if abs(position["size"]) >= moq:
                self.log_info(f"Liquidating current position {position['size']} lot.")
                order_datetime = now_jst()
                if position["side"] == "BUY":
                    order = await self.market_order("SELL", position["size"])
                else:
                    order = await self.market_order("BUY", position["size"])
        self.log_debug("_cancel_and_liquidate end.")


    async def _requests(self, method: str, url: str, params=None, data=None):
        async with pybotters.Client(apis=self.key, base_url='https://api.bitflyer.com') as client:
            return await client.request(method, url=url, params=params, data=data)

    async def _response_json(self, response):
        if not str(response.status).startswith('2'):
            if str(response.status).startswith("4"):
                raise RequestException(f"{response.status} Error {await response.json()}")
            raise RequestException(f"{response.status} Internal Server Error")
        return await response.json()


    async def _replace_order(self, side: str, size: Union[float, int, Decimal], order_type: str, price: any = None,
                             minute_to_expire: int = 43200, time_in_force: str = "GTC"):
        request = {
            "product_code": self.symbol,
            "child_order_type": order_type,
            "side": side,
            "size": float(size),
            "minute_to_expire": minute_to_expire,
            "time_in_force": time_in_force
        }

        if order_type == "LIMIT":
            request["price"] = price

        response = await self._requests('POST', url="/v1/me/sendchildorder", data=request)

        self.api_call_count_from_private += 1
        self.api_call_count_from_order += 1

        return await self._response_json(response)


    async def market_order(self, side: Literal["BUY", "SELL"], size: Union[float, int, Decimal]) -> dict:
        """
        成行注文です
        :param side: buy or sell
        :param size: 数量
        """
        return await self._replace_order(side, size, "MARKET")


    async def limit_order(self, side: Literal["BUY", "SELL"], size: Union[float, int, Decimal], price: any,
                          minute_to_expire: int = 43200, time_in_force: Literal["GTC", "IOC", "FOK"] = "GTC") -> dict:
        """
        指値注文です
        :param side: BUY or SELL
        :param size: 数量
        :param price: 値段
        :param minute_to_expire: 有効期限 分単位
        :param time_in_force:  執行数量条件 "GTC", "IOC", "FOK"のいずれか
        """
        return await self._replace_order(side, size, "LIMIT", price, minute_to_expire, time_in_force)


    async def cancel_order(self, child_order_acceptance_id):
        """
        注文をキャンセルします
        :param child_order_acceptance_id
        """
        data = {
            "product_code": self.symbol,
            "child_order_acceptance_id": child_order_acceptance_id
        }

        response = await self._requests('POST', url="/v1/me/cancelchildorder", data=data)
        await self._response_json(response)

        self.api_call_count_from_private += 1


    async def cancel_all_orders(self):
        """
        全ての注文をキャンセルします
        """
        data = {
            "product_code": self.symbol,
        }

        response = await self._requests('POST', url="/v1/me/cancelallchildorders", data=data)
        await self._response_json(response)

        self.api_call_count_from_private += 1
        self.api_call_count_from_order += 1


    async def _fetch_position(self):
        response = await self._requests("GET", url="/v1/me/getpositions", params={"product_code": self.symbol})
        self.api_call_count_from_private += 1
        return await self._response_json(response)


    async def fetch_my_position(self) -> dict:
        """
        ポジションを取得します.
        :return {"side": side, "size": size}
        """
        response = await self._fetch_position()
        if not response:
            return {}
        else:
            size = sum([Decimal(str(r["size"])) for r in response])
            side = response[0]["side"]
            return {"side": side, "size": size}


    async def manage_order_and_position(self, store):
        """
        pybotters DataStore childorderevents でイベントが起きたときにorderとpositionの管理を行います.
        example response
            self.position = {'side': 'BUY' or 'SELL', 'size': Decimal(size)}
            self.order_acceptanceID = ['JRF20230702-050152-184972']
        """
        # 初期化
        self.position = await self.fetch_my_position()

        try:
            with store.childorderevents.watch() as stream:
                async for msg in stream:
                    event_data = msg.data
                    event_type = event_data['event_type']
                    child_order_acceptance_id = event_data['child_order_acceptance_id']

                    if event_type == 'ORDER':
                        self.order_acceptanceID.append(child_order_acceptance_id)  # 注文IDを追加

                    elif event_type == 'EXECUTION':
                        side = event_data['side']
                        size = Decimal(str(event_data['size']))
                        # positionを計算します.
                        if self.position:
                            current_size = Decimal(str(self.position['size']))
                            if self.position['side'] == 'BUY':
                                if side == 'BUY':
                                    self.position = {'side': 'BUY', 'size': current_size + size}
                                else:
                                    remaining_size = current_size - size
                                    if remaining_size > 0:
                                        self.position = {'side': 'BUY', 'size': remaining_size}
                                    elif remaining_size < 0:
                                        self.position = {'side': 'SELL', 'size': abs(remaining_size)}
                                        if child_order_acceptance_id in self.order_acceptanceID:
                                            self.order_acceptanceID.remove(child_order_acceptance_id)  # 注文を削除
                                    else:
                                        self.position = {}
                                        if child_order_acceptance_id in self.order_acceptanceID:
                                            self.order_acceptanceID.remove(child_order_acceptance_id)
                            else:
                                if side == 'SELL':
                                    self.position = {'side': 'SELL', 'size': current_size + size}
                                else:
                                    remaining_size = current_size - size
                                    if remaining_size > 0:
                                        self.position = {'side': 'SELL', 'size': remaining_size}
                                    elif remaining_size < 0:
                                        self.position = {'side': 'BUY', 'size': abs(remaining_size)}
                                        if child_order_acceptance_id in self.order_acceptanceID:
                                            self.order_acceptanceID.remove(child_order_acceptance_id)
                                    else:
                                        self.position = {}
                                        if child_order_acceptance_id in self.order_acceptanceID:
                                            self.order_acceptanceID.remove(child_order_acceptance_id)
                        else:
                            self.position = {'side': side, 'size': size}
                            if child_order_acceptance_id in self.order_acceptanceID:
                                self.order_acceptanceID.remove(child_order_acceptance_id)

                    else:   # event_type が ORDER_FAILED, CANCEL, CANCEL_FAILED, EXPIREの時の処理
                        if child_order_acceptance_id in self.order_acceptanceID:
                            self.order_acceptanceID.remove(child_order_acceptance_id)

        except ValueError as ve:
            self.log_exception(ve)
        except Exception as e:
            self.log_exception(e)
