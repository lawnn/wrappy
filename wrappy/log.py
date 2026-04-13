import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

class Log(object):
    def __init__(self, path):
        try:
            with open(path, 'r', encoding="utf-8") as fh:
                self.apis = self.config = json.load(fh)
        except FileNotFoundError as e:
            print("[ERROR] Config file is not found.", file=sys.stderr)
            raise e
        except ValueError as e:
            print("[ERROR] Json file is invalid.", file=sys.stderr)
            raise e
        self.logger = None

        try:
            self.exchange_name = self.config["exchange_name"]
        except KeyError:
            self.exchange_name = 'Exchange'
            pass
        try:
            self.bot_name = self.config["bot_name"]
        except KeyError:
            self.bot_name = 'Bot'
        try:
            self.log_level = self.config["log_level"]
        except KeyError:
            self.log_level = 'DEBUG'
        try:
            self.log_dir = self.config["log_dir"]
        except KeyError:
            self.log_dir = 'log'
        self._initialize_logger()

    def _initialize_logger(self):
        """
        ロガーを初期化します.
        """
        if not self.logger:
            self.logger = logging.getLogger(f"{self.exchange_name}_{self.bot_name}")
            self.logger.setLevel(self.log_level)
            self.logger.propagate = False
            if not self.logger.handlers:
                stream_formatter = logging.Formatter(fmt="[%(levelname)s] %(asctime)s : %(message)s",
                                                     datefmt="%Y-%m-%d %H:%M:%S")
                stream_handler = logging.StreamHandler()
                stream_handler.setFormatter(stream_formatter)
                stream_handler.setLevel(self.log_level)
                self.logger.addHandler(stream_handler)
                if self.log_dir:
                    # コンフィグファイルでログディレクトリが指定されていた場合、ファイルにも出力します.
                    os.makedirs(self.log_dir, exist_ok=True)
                    file_formatter = logging.Formatter(fmt="[%(levelname)s] %(asctime)s %(module)s: %(message)s",
                                                       datefmt="%Y-%m-%d %H:%M:%S")
                    file_handler = RotatingFileHandler(
                        filename=os.path.join(self.log_dir, f"{self.exchange_name}_{self.bot_name}.log"),
                        maxBytes=1024 * 1024 * 2, backupCount=3)
                    file_handler.setFormatter(file_formatter)
                    file_handler.setLevel(self.log_level)
                    self.logger.addHandler(file_handler)

    def log_error(self, message):
        """
        ERRORレベルのログを出力します.
        :param message: ログメッセージ.
        """
        self.logger.error(message)

    def log_exception(self, message):
        """
        Exceptionレベルのログを出力します.
        :param message: ログメッセージ.
        """
        self.logger.exception(message)

    def log_warning(self, message):
        """
        WARNINGレベルのログを出力します.
        :param message: ログメッセージ.
        """
        self.logger.warning(message)

    def log_info(self, message):
        """
        INFOレベルのログを出力します.
        :param message: ログメッセージ.
        """
        self.logger.info(message)

    def log_debug(self, message):
        """
        DEBUGレベルのログを出力します.
        :param message: ログメッセージ.
        """
        self.logger.debug(message)
