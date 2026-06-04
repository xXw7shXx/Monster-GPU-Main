import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///bot_data.db")
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    ADMIN_IDS: str
    
    # ITAD
    ITAD_API_KEY: str
    ITAD_APP_ID: str
    
    # IGDB / Twitch
    TWITCH_CLIENT_ID: str
    TWITCH_CLIENT_SECRET: str
    
    # Steam
    STEAM_API_KEY: str
    
    # OpenCritic
    OPENCRITIC_API_KEY: str
    OPENCRITIC_HOST: str = "opencritic-api.p.rapidapi.com"
    
    # RAWG
    RAWG_API_KEY: str
    
    # Gemini
    GEMINI_API_KEY: str = "placeholder"
    GEMINI_PROJECT_NAME: str = "placeholder"
    GEMINI_MODEL_ID: str = "gemini-2.5-flash"
    
    # TikTok
    TIKTOK_CLIENT_KEY: str
    TIKTOK_CLIENT_SECRET: str
    TIKTOK_ACCESS_TOKEN: str = "placeholder"

    # Smart Recommender
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384
    OLLAMA_URL: str = "http://100.116.180.45:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    REC_HISTORY_HOURS: int = 72
    MMR_LAMBDA: float = 0.7
    
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        env_file_encoding="utf-8", 
        extra="ignore"
    )

settings = Settings()
