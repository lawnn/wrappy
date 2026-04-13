import asyncio
import pybotters
from typing import Literal, Union
from decimal import Decimal
from .base import BotBase
from .exceptions import APIException, RequestException


class BitBank(BotBase):
    def __init__(self, config: str, symbol: str):
        super().__init__(config)
        # 通貨ペア
        self.symbol = symbol
        # APIを呼ぶ回数
        self.total_api_call_count = 0
        # API keyの設定
        try:
            self.keys = self.config["bitbank_keys"]
            self.current_key_index = 0
            self.key = {"bitbank": self.keys[self.current_key_index]}
            self.check_keys = True
        except KeyError:
            self.key = {"bitbank": self.config["bitbank"]}
            self.check_keys = False

    async def stop(self):
        """
        ボットを停止します.
        """
        self.log_debug("bitbank stop start")
        super().stop()
        await self._cancel_and_liquidate()
        self.log_debug("bitbank stop end")

    async def _cancel_and_liquidate(self):
        """
        全ての注文をキャンセルした後、ポジションを成行で反対売買してクローズします.
        """
        self.log_debug("_cancel_and_liquidate start.")
        self.log_info("Canceling all open orders.")
        # 全てキャンセル.
        await self.cancel_all_orders()
        await asyncio.sleep(5)
        # 5秒置いてさらに全てキャンセル.
        await self.cancel_all_orders()
        await asyncio.sleep(5)
        position = await self.fetch_my_positions(self.symbol)
        if position['long'] >= 0.0001:
            self.log_info(f"Liquidating Current Long Position {position['long']} lot.")
            await self.liquidate_market_order('sell', position['long'])
        if position['short'] >= 0.0001:
            self.log_info(f"Liquidating Current Short Position {position['short']} lot.")
            await self.liquidate_market_order('buy', position['short'])
        self.log_debug("_cancel_and_liquidate end.")

    async def spot_stop(self):
        """
        ボットを停止します.
        """
        self.log_debug("bitbank stop start")
        super().stop()
        await self.spot_cancel_and_liquidate()
        self.log_debug("bitbank stop end")

    async def spot_cancel_and_liquidate(self):
        """
        全ての注文をキャンセルした後、ポジションを成行で反対売買してクローズします.
        """
        self.log_debug("_cancel_and_liquidate start.")
        self.log_info("Canceling all open orders.")
        # 全てキャンセル.
        await self.cancel_all_orders()
        await asyncio.sleep(5)
        # 5秒置いてさらに全てキャンセル.
        await self.cancel_all_orders()
        await asyncio.sleep(5)
        position = await self.spot_fetch_position()
        if position >= 0.0001:
            self.log_info(f"Liquidating current position {position} lot.")
            await self.spot_market_order("sell", position)
        self.log_debug("_cancel_and_liquidate end.")

    async def _requests(self, method: str, url: str, params=None, data=None):
        # 複数のkeyを使いまわすには"bitbank_keys"をコンフィグに設定します.
        if self.check_keys:
            self.current_key_index = self.total_api_call_count % len(self.keys)
            current_key = {"bitbank": self.keys[self.current_key_index]}
            self.total_api_call_count += 1
        else:
            current_key = self.key

        async with pybotters.Client(apis=current_key, base_url='https://api.bitbank.cc/v1') as client:
            response = await client.request(method, url=url, params=params, data=data)
            if not str(response.status).startswith('2'):
                if str(response.status).startswith("429"):
                    raise RequestException(f"429 Too Many Requests")
                await self.statusNotify(f"Status {response.status} Error")
                raise APIException(response)
            data = await response.json()

            if data["success"] == 0:
                raise RequestException(f"[Error code] {data['data']['code']} Error")
            else:
                return data["data"]

    async def _replace_order(self, side, size, order_type, position_side=None, price: any = None, post_only: bool = False, trigger_price: str = None):
        request = {
            "pair": self.symbol,
            "amount": str(size),
            "side": side,
            "position_side": position_side,
            "type": order_type,
            "post_only": post_only,
            }

        if order_type == "limit":
            request["price"] = str(price)
        if order_type == "stop" or order_type == "stop_limit":
            request["trigger_price"] = str(trigger_price)

        return await self._requests('POST', url="/user/spot/order", data=request)

    async def market_order(self, side: Literal['buy', 'sell'], size: Union[float, int, Decimal]) -> dict:
        """
        信用取引の成行注文です
        :param side: buy or sell
        :param size: 数量
        """
        if side == 'buy':
            position_side = 'long'
        else:
            position_side = 'short'
        return await self._replace_order(side, size, "market", position_side=position_side)

    async def liquidate_market_order(self, side: Literal['buy', 'sell'], size: Union[float, int, Decimal]) -> dict:
        """
        信用取引の清算成行注文です
        longポジションを決済する場合は side=sell
        shortポジションを決済する場合は side=buy
        :param side: buy or sell
        :param size: 数量
        """
        if side == 'buy':
            position_side = 'short'
        else:
            position_side = 'long'
        return await self._replace_order(side, size, "market", position_side=position_side)

    async def spot_market_order(self, side: Literal['buy', 'sell'], size: Union[float, int, Decimal]) -> dict:
        """
        現物の成行注文です
        :param side: buy or sell
        :param size: 数量
        """
        return await self._replace_order(side, size, "market")

    async def limit_order(self, side: Literal['buy', 'sell'], size: Union[float, int, Decimal], price: Union[float, int, Decimal], post_only: bool = False) -> dict:
        """
        信用取引の指値注文です
        :param side: buy or sell
        :param size: 数量
        :param price: 値段
        :param post_only: 必ずMakerの注文にするか否か Takerの注文の場合発注されません True or False
        """
        if side == 'buy':
            position_side = 'long'
        else:
            position_side = 'short'
        return await self._replace_order(side, size, order_type="limit", price=price, post_only=post_only, position_side=position_side)

    async def liquidate_limit_order(self, side: Literal['buy', 'sell'], size: Union[float, int, Decimal], price: Union[float, int, Decimal], post_only: bool = False) -> dict:
        """
        信用取引の指値清算注文です
        :param side: buy or sell
        :param size: 数量
        :param price: 値段
        :param post_only: 必ずMakerの注文にするか否か Takerの注文の場合発注されません True or False
        """
        if side == 'buy':
            position_side = 'short'
        else:
            position_side = 'long'
        return await self._replace_order(side=side, size=size, order_type="limit", price=price, post_only=post_only, position_side=position_side)

    async def spot_limit_order(self, side: Literal['buy', 'sell'], size: Union[float, int, Decimal], price: Union[float, int, Decimal], post_only: bool = False) -> dict:
        """
        現物の指値注文です
        :param side: buy or sell
        :param size: 数量
        :param price: 値段
        :param post_only: 必ずMakerの注文にするか否か Takerの注文の場合発注されません True or False
        """
        try:
            return await self._replace_order(side=side, size=size, order_type="limit", price=price, post_only=post_only)
        except RequestException as e:
            self.log_exception(f"API request failed in limit_order.")
            raise e
        except Exception as e:
            self.log_exception("API request failed in limit_order.")
            raise e

    async def fetch_balance(self) -> dict:
        """
        口座情報を取得します
        """
        return await self._requests("GET", url="/user/assets")

    async def _fetch_active_order(self) -> dict:
        """
        注文中の情報を取得します
        """
        return await self._requests("GET", url="/user/spot/active_orders", params={"pair": self.symbol})

    async def _fetch_order_info(self, order_id: int) -> dict:
        """
        注文の情報を取得します(単品)
        主に非アクティブな情報を取得することに使います
        """
        return await self._requests("GET", url="/user/spot/order", params={"pair": self.symbol, "order_id": order_id})

    async def _fetch_orders_info(self, order_ids: list) -> dict:
        """
        注文の情報を取得します(複数)
        主に非アクティブな情報を取得することに使います
        """
        return await self._requests("POST", url="/user/spot/orders_info", data={"pair": self.symbol, "order_ids": order_ids})

    async def fetch_trades_history(self) -> dict:
        """
        自分の約定履歴を取得します
        """
        return await self._requests("GET", url="/user/spot/trade_history", params={"pair": self.symbol})

    async def fetch_open_orders(self) -> list:
        """
        注文中の全てのorder idを取得します
        :return:
        """
        try:
            open_orders = await self._fetch_active_order()
            return [open_orders["orders"][i]["order_id"]
                    for i in range(len(open_orders["orders"]))
                    if open_orders["orders"][i]["status"] == "UNFILLED"
                    or open_orders["orders"][i]["status"] == "PARTIALLY_FILLED"]
        except Exception as e:
            self.log_exception("API request failed in fetch_open_order.")
            raise e

    async def spot_fetch_position(self) -> str:
        """
        現物の建玉情報です
        ポジション数を取得します
        実行すると取得系APIを一度に2回消費します
        """
        try:
            balance = await self.fetch_balance()
            open_orders = await self._fetch_active_order()
            symbol = self.symbol.replace("_jpy", "")
            position = "0"

            for i in range(1, len(balance["assets"])):
                if balance["assets"][i]["asset"].startswith(symbol):
                    position = Decimal(balance["assets"][i]["free_amount"])
                    break

            remaining_amount = sum([Decimal(order["remaining_amount"])
                                    for order in open_orders["orders"]
                                    if order["side"] == "sell"])

            return str((position + remaining_amount).normalize())
        except RequestException as e:
            raise e
        except Exception as e:
            self.logger.exception("API request failed in spot_fetch_my_position.")
            raise e

    async def fetch_positions(self):
        """信用取引の建玉情報です
        主にpositionsに建玉の情報が入ります
        {
            "notice": {
            "what": "string",
            "occurred_at": 0,
            "amount": "0",
            "due_date_at": 0
            },
            "payables": {
            "amount": "0"
            },
            "positions": [
            {
                "pair": "string",
                "position_side": "string",
                "open_amount": "0",
                "product": "0",
                "average_price": "0",
                "unrealized_fee_amount": "0",
                "unrealized_interest_amount": "0"
            }
            ],
            "losscut_threshold": {
            "individual": "0",
            "company": "0"
            }
        }
        """
        return await self._requests("GET", url="/user/margin/positions")

    async def fetch_my_positions(self, symbol) -> dict:
        """
        信用取引の建玉を辞書にまとめたものです
        {
        long: longポジション数量,
        short: shortポジション数量
        }
        """
        pos = await self.fetch_positions()
        for i in range(len(pos['positions'])):
            if pos['positions'][i]['pair'] == symbol:
                if pos['positions'][i]['position_side'] == 'long':
                    long_pos = pos['positions'][i]['open_amount']
                else:
                    short_pos = pos['positions'][i]['open_amount']
        return {
            'long': Decimal(long_pos),
            'short': Decimal(short_pos)
            }

    async def cancel_and_fetch_position(self) -> float:
        """
        ポジション数を取得します
        実行すると取得系APIを2回,注文系を1回消費します
        注文をキャンセルしつつポジション数を取得したいときに使います
        """
        try:
            await self.cancel_all_orders()
            symbol = self.symbol.replace("_jpy", "")
            balance = await self.fetch_balance()
            for i in range(1, len(balance["assets"])):
                if balance["assets"][i]["asset"].startswith(symbol):
                    return float(balance["assets"][i]["free_amount"])

        except RequestException as e:
            raise e
        except Exception as e:
            self.logger.exception("API request failed in cancel_and_fetch_position.")
            raise e

    async def _cancel_order(self, order_id: int) -> any:
        """
        単品の注文をキャンセルします
        """
        try:
            return await self._requests("POST", url="/user/spot/cancel_order", data={"pair": self.symbol, "order_id":order_id})
        except APIException as e:
            if e.status == 404:
                return None
            else:
                raise e
        except RequestException as e:
            raise e

    async def _cancel_any_orders(self, order_ids: list) -> any:
        """
        いくつかの注文をキャンセルします
        """
        try:
            return await self._requests("POST", url="/user/spot/cancel_orders", data={"pair": self.symbol, "order_ids": order_ids})
        except APIException as e:
            if str(e.status).startswith("404"):
                return None
            else:
                self.log_exception("API request failed in cancel orders.")
                raise e
        except RequestException as e:
            raise e

    async def cancel_all_orders(self):
        """
        全ての注文をキャンセルします
        取得系APIを1回,注文系APIを1回消費します
        """
        try:
            open_orders = await self.fetch_open_orders()
            return await self._cancel_any_orders(open_orders)
        except RequestException as e:
            if str(e).startswith("40014", 35):
                return None
        except Exception as e:
            self.logger.exception("API request failed in cancel_all_orders.")
            raise e

    async def exchange_status(self) -> dict:
        """
        サーバーの状態を見たいときに使います
        """
        try:
            return await self._requests("GET", url="/spot/status")
        except Exception as e:
            self.log_exception("API request failed in exchange status")
            raise e
