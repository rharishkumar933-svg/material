from pyrogram import Client
from bot.config import Config
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

class Bot(Client):
    def __init__(self):
        super().__init__(
            "material_unlock_bot",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            plugins=dict(root="bot/plugins"),
            in_memory=True
        )

if __name__ == "__main__":
    print("Starting Material Unlock Bot...")
    Bot().run()
