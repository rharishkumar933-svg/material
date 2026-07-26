import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    MONGODB_URL = os.getenv("MONGODB_URL", "")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "material_unlock_bot")
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    
    # Message Deletion Time (in seconds)
    DELETE_TIME = 60
    
    # Global Force Subscribe Channel
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
    CHANNEL_LINK = os.getenv("CHANNEL_LINK", "")
