import aiohttp
from .log import Log

class Notify(Log):
    def __init__(self, path):
        super().__init__(path)

        # ラインに稼働状況を通知
        try:
            self.line_notify_token = self.config["line_notify_token"]
        except KeyError:
            self.line_notify_token = None
        # Discordに稼働状況を通知するWebHook
        try:
            self.discordWebhook = self.config["discordWebhook"]
        except KeyError:
            # 設定されていなければNoneにしておく
            self.discordWebhook = None

    async def lineNotify(self, message, fileName=None):
        if not self.line_notify_token:
            raise ValueError("line_notify_token is not configured.")

        payload = {'message': message}
        headers = {'Authorization': 'Bearer ' + self.line_notify_token}
        async with aiohttp.ClientSession() as session:
            if fileName is None:
                try:
                    await session.post('https://notify-api.line.me/api/notify', data=payload, headers=headers)
                    self.log_info(message)
                except Exception as e:
                    self.log_error(e)
                    raise e
            else:
                try:
                    with open(fileName, "rb") as fh:
                        data = aiohttp.FormData()
                        data.add_field("message", message)
                        data.add_field("imageFile", fh, filename=fileName)
                        await session.post(
                            'https://notify-api.line.me/api/notify',
                            data=data,
                            headers=headers,
                        )
                except Exception as e:
                    self.log_error(e)
                    raise e

    # config.json内の[discordWebhook]で指定されたDiscordのWebHookへの通知
    async def discordNotify(self, message, file_path=None):
        payload = {"content": " " + message + " "}
        async with aiohttp.ClientSession() as session:
            if file_path is None:
                try:
                    await session.post(self.discordWebhook, data=payload)
                    self.log_info(message)
                except Exception as e:
                    self.log_error(e)
                    raise e
            else:
                try:
                    with open(file_path, 'rb') as f:
                        data = aiohttp.FormData()
                        data.add_field('file', f, filename='image.png', content_type='image/png')
                        await session.post(self.discordWebhook, data=data)
                except Exception as e:
                    self.log_error(e)
                    raise e

    async def statusNotify(self, message, fileName=None):
        if not self.discordWebhook and not self.line_notify_token:
            self.log_warning("Notification skipped because no Discord webhook or LINE token is configured.")
            return None

        # config.json内に[discordWebhook]が設定されていなければLINEへの通知
        if self.discordWebhook is None:
            await self.lineNotify(message, fileName)
        else:
            # config.json内に[discordWebhook]が設定されていればDiscordへの通知
            await self.discordNotify(message, fileName)
