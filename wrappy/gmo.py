import pybotters
import asyncio
from pybotters.helpers import GMOCoinHelper
from decimal import Decimal
from typing import Literal, Union
from .time_util import now_jst
from .base import BotBase
from .exceptions import RequestException

class GMO(BotBase):
    def __init__(self, config: str, symbol: str):
        super().__init__(config)
        self.symbol = symbol
        # API keyの設定
        self.key = {"gmocoin": self.config["gmocoin"]}
        # position
        self.position = {}

    async def _requests(self, method: str, url: str, params=None, data=None):
        async with pybotters.Client(apis=self.key, base_url='https://api.coin.z.com') as client:
            r = await client.request(method, url=url, params=params, data=data)
            if not str(r.status).startswith('2'):
                raise RequestException(f"[{r.status}] server error")
            data = await r.json()
            if not data['status'] == 0:
                messages = data.get("messages") or []
                if messages:
                    err_code = messages[0].get('message_code', 'UNKNOWN')
                    err_msg = str(messages[0].get('message_string', data))
                else:
                    err_code = data.get("status", "UNKNOWN")
                    err_msg = str(data)
                raise RequestException(f"[Error code] {err_code} [Error msg] {err_msg}")
            else:
                if "data" in data:
                    return data["data"]
                else:
                    return data

    async def stop(self):
        """
        ボットを停止します.
        """
        self.log_debug("gmocoin stop start")
        super().stop()
        await self._cancel_and_liquidate()
        self.log_debug("gmocoin stop end")


    async def _cancel_and_liquidate(self, moq = 0.01):
        """
        全ての注文をキャンセルした後、ポジションを成行で反対売買してクローズします.
        :param moq(Minimum Order Quantity)最小ロットです
        """
        self.log_debug("_cancel_and_liquidate start.")
        self.log_info("Canceling all open orders.")
        # 全てキャンセル.
        await asyncio.sleep(1)
        await self.cancel_all_orders()
        # 5秒置いてさらに全てキャンセル.
        await asyncio.sleep(5)
        await self.cancel_all_orders()
        position_list = await self.position_summary(self.symbol)
        if position_list["list"]:
            for i in range(len(position_list["list"])):
                size = position_list["list"][i]['sumPositionQuantity']
                if position_list["list"][i]["side"] == "BUY":
                    side = "SELL"
                else:
                    side = "BUY"

                if Decimal(size) >= Decimal(str(moq)):
                    order_id = await self.liquidate_order_market(side, size)
                    self.log_info(f"Liquidating current position {size} lot.")
        self.log_debug("_cancel_and_liquidate end.")

    async def account_margin(self):
        """
        余力情報を取得
        :return:
        {
          "status": 0,
          "data": {
            "actualProfitLoss": "5204923",  時価評価総額
            "availableAmount": "5189523",   取引余力
            "margin": "7298",               拘束証拠金
            "marginCallStatus": "NORMAL",   追証ステータス: NORMAL MARGIN_CALL LOSSCUT
            "marginRatio": "345.6",         証拠金維持率
            "profitLoss": "8019"            評価損益
          },
          "responsetime": "2019-03-19T02:15:06.051Z"
        }
        """
        return await self._requests('GET', '/private/v1/account/margin')

    async def account_assets(self):
        """
        資産残高を取得
        :return:
        {
          "status": 0,
          "data": [
            {
              "amount": "993982448",      残高
              "available": "993982448",   利用可能金額（残高 - 出金予定額）
              "conversionRate": "1",      円転レート（販売所での売却価格です）
              "symbol": "JPY"             ※取引所（現物取引）の取扱銘柄のみAPIでご注文いただけます。
            },
            {
              "amount": "4.0002",           残高
              "available": "4.0002",        利用可能金額（残高 - 出金予定額）
              "conversionRate": "859614",   円転レート（販売所での売却価格です）
              "symbol": "BTC"               ※取引所（現物取引）の取扱銘柄のみAPIでご注文いただけます。
            }
          ],
          "responsetime": "2019-03-19T02:15:06.055Z"
        }
        """
        return await self._requests('GET', '/private/v1/account/assets')

    async def orders(self, orderId):
        """
        注文情報取得
        :return:
        {
          "status": 0,
          "data": {
            "list": [
              {
                "orderId": 223456789,       親注文ID
                "rootOrderId": 223456789,   注文ID
                "symbol": "BTC_JPY",
                "side": "BUY",
                "orderType": "NORMAL",      取引区分: NORMAL LOSSCUT
                "executionType": "LIMIT",   注文タイプ: MARKET LIMIT STOP
                "settleType": "OPEN",       決済区分: OPEN CLOSE
                "size": "0.02",             発注数量
                "executedSize": "0.02",     約定数量
                "price": "1430001",         注文価格 (MARKET注文の場合は"0")
                "losscutPrice": "0",        ロスカットレート (現物取引や未設定の場合は"0")
                "status": "EXECUTED",       注文ステータス: WAITING ORDERED MODIFYING CANCELLING CANCELED EXECUTED EXPIRED
                                            ※逆指値注文の場合はWAITINGが有効
                "timeInForce": "FAS",       執行数量条件: FAK FAS FOK (Post-onlyの場合はSOK)
                "timestamp": "2020-10-14T20:18:59.343Z"
              },
              {
                "rootOrderId": 123456789,
                "orderId": 123456789,
                "symbol": "BTC",
                "side": "BUY",
                "orderType": "NORMAL",
                "executionType": "LIMIT",
                "settleType": "OPEN",
                "size": "1",
                "executedSize": "0",
                "price": "900000",
                "losscutPrice": "0",
                "status": "CANCELED",
                "cancelType": "USER",
                "timeInForce": "FAS",
                "timestamp": "2019-03-19T02:15:06.059Z"
              }
            ]
          },
          "responsetime": "2019-03-19T02:15:06.059Z"
        }
        """
        params = {"orderId": f'{orderId}'}
        return await self._requests('GET', '/private/v1/orders', params=params)

    async def active_orders(self, symbol: str, page: int = 1, count: int = 100):
        """
        有効注文一覧
        :return:
        {
          "status": 0,
          "data": {
            "pagination": {
              "currentPage": 1,
              "count": 30
            },
            "list": [
              {
                "rootOrderId": 123456789,   親注文ID
                "orderId": 123456789,       注文ID
                "symbol": "BTC",
                "side": "BUY",
                "orderType": "NORMAL",
                "executionType": "LIMIT",
                "settleType": "OPEN",
                "size": "1",                発注数量
                "executedSize": "0",        約定数量
                "price": "840000",
                "losscutPrice": "0",
                "status": "ORDERED",
                "timeInForce": "FAS",
                "timestamp": "2019-03-19T01:07:24.217Z"
              }
            ]
          },
          "responsetime": "2019-03-19T01:07:24.217Z"
        }
        """
        return await self._requests('GET', '/private/v1/activeOrders',
                                    params={"symbol": symbol, "page": page, "count": count})

    async def fetch_all_order_id(self) -> list:
        """
        アクティブオーダーを取得します.
        """
        try:
            active_orders = await asyncio.wait_for(self.active_orders(self.symbol), timeout=2)
            if active_orders:
                order_ids = [item['orderId'] for item in active_orders['list']]
                return order_ids
            else:
                return active_orders
        except RequestException as e:
            self.log_warning(e)
            return []
        except TimeoutError as e:
            self.log_warning(e)
            return []



    async def executions(self, *Id, id_kind="orderId"):
        """
        約定情報取得
        orderId executionId いずれか一つが必須です。2つ同時には設定できません。
        下記いずれかのIDを引数に入れます(ID number複数可能)
        id_kind: orderId or executionId
        Id: 3215487
        
        responce: 
        {
          "status": 0,
          "data": {
            "list": [
              {
                "executionId": 92123912,
                "orderId": 223456789,
                "positionId": 1234567,
                "symbol": "BTC_JPY",
                "side": "BUY",
                "settleType": "OPEN",
                "size": "0.02",
                "price": "1900000",
                "lossGain": "0",
                "fee": "223",
                "timestamp": "2020-11-24T21:27:04.764Z"
              },
              {
                "executionId": 72123911,
                "orderId": 123456789,
                "positionId": 1234567,
                "symbol": "BTC",
                "side": "BUY",
                "settleType": "OPEN",
                "size": "0.7361",
                "price": "877404",
                "lossGain": "0",
                "fee": "323",
                "timestamp": "2019-03-19T02:15:06.081Z"
              }
            ]
          },
          "responsetime": "2019-03-19T02:15:06.081Z"
        }
        """
        if id_kind == "orderId":
          params = {"orderId": f"{Id}"}
        elif id_kind == "executionId":
          params = {"executionId": f"{Id}"}
        else:
          raise ValueError
        return await self._requests('GET', '/private/v1/executions', params=params)

    async def latest_executions(self, symbol: str, page: int = 1, count: int = 100):
        """
        最新の約定一覧
        直近1日分の約定情報を返します。
        :return:
        {
          "status": 0,
          "data": {
            "pagination": {
              "currentPage": 1,
              "count": 30
            },
            "list": [
              {
                "executionId": 72123911,
                "orderId": 123456789,
                "positionId": 1234567,
                "symbol": "BTC",
                "side": "BUY",
                "settleType": "OPEN",
                "size": "0.7361",
                "price": "877404",
                "lossGain": "0",        決済損益
                "fee": "323",           取引手数料
                                        ※Takerの場合はプラスの値、Makerの場合はマイナスの値が返ってきます。
                "timestamp": "2019-03-19T02:15:06.086Z"
              }
            ]
          },
          "responsetime": "2019-03-19T02:15:06.086Z"
        }
        """
        return await self._requests('GET', '/private/v1/latestExecutions',
                                    params={"symbol": symbol, "page": page, "count": count})

    async def open_positions(self, symbol: str, page: int = 1, count: int = 100):
        """
        建玉一覧を取得
        有効建玉一覧を取得します。
        :return:
        {
          "status": 0,
          "data": {
            "pagination": {
              "currentPage": 1,
              "count": 30
            },
            "list": [
              {
                "positionId": 1234567,
                "symbol": "BTC_JPY",
                "side": "BUY",
                "size": "0.22",
                "orderdSize": "0",      発注中数量
                "price": "876045",
                "lossGain": "14",
                "leverage": "4",
                "losscutPrice": "766540",
                "timestamp": "2019-03-19T02:15:06.094Z"
              }
            ]
          },
          "responsetime": "2019-03-19T02:15:06.095Z"
        }
        """
        return await self._requests('GET', '/private/v1/openPositions',
                                   params={"symbol": symbol, "page": page, "count": count})

    async def position_summary(self, symbol: str=None):
        """
        建玉サマリーを取得
        指定した銘柄の建玉サマリーを売買区分(買/売)ごとに取得ができます
        symbolパラメータ指定無しの場合は、保有している全銘柄の建玉サマリーを売買区分(買/売)ごとに取得します。
        :return:
            "list": [
              {
                "averagePositionRate": "715656",    平均建玉レート
                "positionLossGain": "250675",       評価損益
                "side": "BUY",                      売買区分: BUY SELL
                "sumOrderQuantity": "2",            発注中数量
                "sumPositionQuantity": "11.6999",   建玉数量
                "symbol": "BTC_JPY"
              }
            ]
        """
        return await self._requests('GET', '/private/v1/positionSummary', params={"symbol": symbol})

    async def fetch_my_position(self):
        data = await self.position_summary(self.symbol)
        if data["list"]:
            return {"side": data["list"][0]["side"], "size": Decimal(data["list"][0]["sumPositionQuantity"])}
        else:
            return {}

    async def _replace_order(self, side: str,
                             size: Union[float, int, Decimal],
                             order_type: Literal["MARKET", "LIMIT", "STOP"],
                             price: Union[float, int, Decimal] = None,
                             create_or_liquidate: Literal["create", "liquidate", "liquidate_all"] = None,
                             positionId: int = None,
                             timeInForce: Literal["FAK", "FAS", "FOK", "SOK"] = None,
                             losscut_price: Union[float, int, Decimal, str] = None,
                             cancelBefore: bool = False):
        data = {
            "symbol": self.symbol,
            "side": side,
            "executionType": order_type,
            "timeInForce": timeInForce,
            "losscutPrice": losscut_price,
            "cancelBefore": cancelBefore
        }

        if create_or_liquidate == 'create':    # 新規の注文
            url = '/private/v1/order'
            data["size"] = str(size)
        elif create_or_liquidate == 'liquidate':  # positionId毎に決済
            url = '/private/v1/closeOrder'
            data["settlePosition"] = [{"positionId": positionId, "size": str(size)}]
        else:   # 全てのポジションを決済
            url = '/private/v1/closeBulkOrder'
            data["size"] = str(size)

        if (order_type == 'LIMIT') or (order_type == 'STOP'):
            data['price'] = str(price)

        return await self._requests('POST', url=url, data=data)

    async def market_order(self, side: Literal["BUY", "SELL"], size: Union[float, int, Decimal],
                           timeInForce: Literal["FAK", "FAS", "FOK", "SOK"] = None,
                           cancelBefore: bool = False):
        """
        新規の成行注文
        :param cancelBefore:
        :param timeInForce:
        :param side:
        :param size:
        :return:
                   {"status": 0,
                    "data": "637000", (orderID)
                    "responsetime": "2019-03-19T02:15:06.108Z"}
        """
        return await self._replace_order(side, size, 'MARKET', create_or_liquidate="create",
                                         timeInForce=timeInForce, cancelBefore=cancelBefore)

    async def stop_order(self, side: Literal["BUY", "SELL"], size: Union[float, int, Decimal], price: Union[float, int, Decimal],
                         cancelBefore: bool = False
                         ):
      """ストップ注文
      成行注文にストップ注文をします
      :param side:
      :param size:
      :param price:
      :return:
          {"status": 0,
          "data": "637000", (orderID)
          "responsetime": "2019-03-19T02:15:06.108Z"}
      """
      return await self._replace_order(side, size, 'STOP', price=price, create_or_liquidate="create",
                                  cancelBefore=cancelBefore)

    async def limit_order(self, side: Literal["BUY", "SELL"], size: Union[float, int, Decimal], price: Union[float, int, Decimal],
                          timeInForce: Literal["FAK", "FAS", "FOK", "SOK"] = None,
                          losscut_price: Union[float, int, Decimal, str] = None,
                          cancelBefore: bool = False
                          ):
        """
        新規の指値注文
        :param cancelBefore:
        :param timeInForce:
        :param side:
        :param size:
        :param price:
        :return:
           {"status": 0,
            "data": "637000", (orderID)
            "responsetime": "2019-03-19T02:15:06.108Z"}
        """
        return await self._replace_order(side, size, 'LIMIT', price=price, create_or_liquidate="create",
                                         timeInForce=timeInForce, losscut_price=losscut_price, cancelBefore=cancelBefore)

    async def settle_market(self, side: str, size: Union[float, int, Decimal], positionId: int,
                           timeInForce: Literal["FAK", "FAS", "FOK", "SOK"] = None,
                           cancelBefore: bool = False):
        """
        指定されたポジションIDを成行決済します
        :param timeInForce:
        :param cancelBefore:
        :param side:
        :param size:
        :param positionId:
        :return:
            {"status": 0,
            "data": "637000", (orderID)
            "responsetime": "2019-03-19T02:15:06.108Z"}
        """
        return await self._replace_order(side, size, 'MARKET', create_or_liquidate="liquidate", positionId=positionId,
                                         timeInForce=timeInForce, cancelBefore=cancelBefore)

    async def settle_limit(self, side: str, size: Union[float, int, Decimal], price: Union[float, int, Decimal], positionId: int,
                           timeInForce: Literal["FAK", "FAS", "FOK", "SOK"] = None,
                           cancelBefore: bool = False):
        """
        指定されたポジションIDを指値決済します
        :param timeInForce:
        :param cancelBefore:
        :param side:
        :param size:
        :param price:
        :param positionId:
        :return:
                    {"status": 0,
                    "data": "637000", (orderID)
                    "responsetime": "2019-03-19T02:15:06.108Z"}
        """
        return await self._replace_order(side, size, 'LIMIT', price=price, create_or_liquidate="liquidate",
                                         positionId=positionId, timeInForce=timeInForce, cancelBefore=cancelBefore)

    async def liquidate_order_market(self, side: str, size: Union[float, int, Decimal],
                           timeInForce: Literal["FAK", "FAS", "FOK", "SOK"] = None,
                           cancelBefore: bool = False):
        """
        一括成行決済注文
        :param timeInForce:
        :param cancelBefore:
        :param side:
        :param size:
        :return:
           {"status": 0,
            "data": "637000", (orderID)
            "responsetime": "2019-03-19T02:15:06.108Z"}
        """
        return await self._replace_order(side, size, 'MARKET', create_or_liquidate="liquidate_all",
                                         timeInForce=timeInForce, cancelBefore=cancelBefore)

    async def liquidate_order_limit(self, side: str, size: Union[float, int, Decimal], price: Union[float, int, Decimal],
                           timeInForce: Literal["FAK", "FAS", "FOK", "SOK"] = None,
                           cancelBefore: bool = False):
        """
        一括指値決済注文
        :param timeInForce:
        :param cancelBefore:
        :param side:
        :param size:
        :param price:
        :return:
           {"status": 0,
            "data": "637000",       orderID
            "responsetime": "2019-03-19T02:15:06.108Z"}
        """
        return await self._replace_order(side, size, 'LIMIT', price=price, create_or_liquidate="liquidate_all",
                                         timeInForce=timeInForce, cancelBefore=cancelBefore)

    async def cancel_order(self, order_id: Union[int, str]):
        """
        注文キャンセル
        :param order_id:
        :return:
        "result": "Order queued for cancelation"
        {
          "status": 0,
          "responsetime": "2019-03-19T01:07:24.557Z"
        }
        """
        return await self._requests('POST', '/private/v1/cancelOrder', data={'orderId': order_id})

    async def cancel_any_orders(self, order_id: list):
        """
        注文の複数キャンセル 約定などの理由でIDが無かった場合はfailedに情報が載ります
        :order_id: [1,2,3,4]
        :return:
        "result": "Orders queued for cancelation"
        {
              "failed": [
                {
                  "message_code": "ERR-5122",
                  "message_string": "The request is invalid due to the status of the specified order.",
                  "orderId": 1
                },
                {
                  "message_code": "ERR-5122",
                  "message_string": "The request is invalid due to the status of the specified order.",
                  "orderId": 2
                }
              ],
              "success": [3,4]
        }
        """
        return await self._requests('POST', '/private/v1/cancelOrders', data={'orderIds': order_id})

    async def cancel_all_orders(self, side: Literal["BUY", "SELL"] = None, settleType: Literal["OPEN", "CLOSE"] = None,
                                desc: bool = None):
        """
        全ての注文をキャンセルします(取消対象検索後に、最大10件まで注文を取消します。)
        :param desc: true の場合、注文日時が新しい注文から取消します。false の場合、注文日時が古い注文から取消します。指定がない場合はfalse
        :param settleType: OPEN CLOSE 指定時のみ、現物取引注文と指定された決済区分のレバレッジ取引注文を取消対象にします。
        :param side: BUY SELL 指定時のみ、指定された売買区分の注文を取消対象にします。
        :return: [637000,637002]
        """
        return await self._requests('POST', '/private/v1/cancelBulkOrder',
                                   data={"symbols": [self.symbol], "side": side, "settleType": settleType, "desc": desc})

    async def edit_order(self, orderId: int, price: Union[int,float], losscutPrice: Union[int,float] = None):
        """
        注文変更
        :param losscutPrice:
        :param orderId:
        :param price:
        :return:
        {
          "status": 0,
          "responsetime": "2019-03-19T01:07:24.557Z"
        }
        """
        return await self._requests('POST', '/private/v1/changeOrder',
                                    data={"orderId": orderId, "price": price, "losscutPrice": losscutPrice})

    async def historical(self, symbol: str, interval: str, date: str):
        return await self._requests('GET', f'/public/v1/klines',
                                    params={"symbol": symbol, 'interval': interval, 'date': date})

    # websocket
    async def gmo_ws(self, client, store, *subscriptions):
        """ exsample code
        params = [{"command": "subscribe", "channel": "orderbooks", "symbol": self.symbol},
                  {"command": "subscribe", "channel": "trades", "symbol": self.symbol}]
        async with pybotters.Client() as client:
            await self.ws(client, store, *params)
        """
        subscription_commands = [{"command": subscription["command"], "channel": subscription["channel"], "symbol": subscription["symbol"]} for subscription in subscriptions]
        await self.ws('wss://api.coin.z.com/ws/public/v1', client, store, subscription_commands)

    # private websocket
    async def gmo_priv_ws(self, client, store, *subscriptions):
        """ example code
        購読したいchannelを指定
        priv_gmo_subscriptions = [
                        {"command": "subscribe", "channel": "positionEvents"},
                        {"command": "subscribe", "channel": "orderEvents"}
                        ]
        async with pybotters.Client() as client:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self.gmo_priv_ws(client, store, *priv_gmo_subscriptions))
                それか
                # tg.create_task(self.gmo_priv_ws(client, store, {"command": "subscribe", "channel": "positionEvents"}, {"command": "subscribe", "channel": "orderEvents"}))
        """
        # Create a helper instance for GMOCoin.
        gmohelper = GMOCoinHelper(client)

        # Alias for POST /private/v1/ws-auth.
        token = await gmohelper.create_access_token()

        # サブスクリプションコマンドのリストを動的に構築する。
        subscription_commands = []
        for subscription in subscriptions:
            command = {"command": subscription["command"], "channel": subscription["channel"]}
            if "option" in subscription:
                command["option"] = subscription["option"]
            subscription_commands.append(command)

        ws = await client.ws_connect(
            f"wss://api.coin.z.com/ws/private/v1/{token}",
            send_json=subscription_commands,
            hdlr_json=store.onmessage
        )
        async with asyncio.TaskGroup() as tg:
            tg.create_task(gmohelper.manage_ws_token(ws, token))
