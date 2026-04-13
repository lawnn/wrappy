from .notify import Notify

class BotBase(Notify):
    def __init__(self, path):
        super().__init__(path)
        self.stop_flag = False
        # 発注履歴ファイルを保存するファイルのパラメータ
        try:
            self.order_history_dir = self.config["log_dir"]
        except KeyError:
            self.order_history_dir = 'log'
        self.columns = {}
        # csvファイルを書き込む場所
        self.target_csv_file = f"{self.exchange_name}_{self.bot_name}_order_history.csv"
        # 発注履歴ファイルを保存するファイルのパラメータ
        self.fieldnames = [
                        "order_no",          # オーダーNo.
                        "order_id",          # オーダーID
                        "timestamp",         # オーダー時刻
                        "order_kind",        # オーダー種別
                        "size",              # 実際にオーダーしたサイズ
                        "price",             # 実際にオーダーした価格
                        "current_position"   # 現在ポジション
                        ]
        """csvio 簡単な使い方
        from csvio import CSVWriter
        writer = CSVWriter(self.target_csv_file, fieldnames=self.fieldnames)
        order_history = {
                        "order_no": 123,
                        "order_id": 456789,
                        "timestamp": '2024-09-06 22:31:41',
                        "order_kind": "ask",
                        "size": 1,
                        "price": 1000000,
                        "current_position": 2,
                        }
        writer.add_rows(order_history) row追加
        writer.flush()  csv書き込み
        """
        

    async def start(self):
        """
        ボットを起動します.
        """
        self.log_info("Bot started.")
        await self._run_logic()

    def stop(self):
        """
        ボットを停止します.
        """
        self.stop_flag = True
        self.log_info("Logic has been stopped.")

    async def _run_logic(self):
        """
        ロジック部分です. 子クラスで実装します.
        """
        raise NotImplementedError()

    async def ws(self, url, client, store, subscription_commands):
        """
        websocketのベースです
        """
        await client.ws_connect(
            url,
            send_json=subscription_commands,
            hdlr_json=store.onmessage)
