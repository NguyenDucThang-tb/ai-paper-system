import os
from pathlib import Path
from dotenv import load_dotenv

# ✅ Luôn load .env theo file này, KHÔNG theo cwd
BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"


load_dotenv(dotenv_path=ENV_PATH)

class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "ai-paper-system")
    ENV: str = os.getenv("ENV", "development")

    SECRET_KEY: str | None = os.getenv("SECRET_KEY")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    INTERNAL_API_TOKEN: str | None = os.getenv("INTERNAL_API_TOKEN")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
    )

    DATABASE_URL: str | None = os.getenv("DATABASE_URL")

    def __init__(self):
        print("🔑 ENV_PATH =", ENV_PATH)
        print("🔑 SECRET_KEY =", repr(self.SECRET_KEY))
        if not isinstance(self.SECRET_KEY, str):
            raise RuntimeError("❌ SECRET_KEY is missing or not a string")

settings = Settings()
