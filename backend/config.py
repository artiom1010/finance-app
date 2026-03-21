import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DB_PATH: str = os.getenv("DB_PATH", "data/finance.db")
DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")
