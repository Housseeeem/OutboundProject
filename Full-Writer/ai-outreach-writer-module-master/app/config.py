from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # App
    APP_NAME: str = "Agentic Outreach API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8003
    
    # Worker API
    WORKER_URL: str = "http://api:8000"
    
    # Google Gemini
    GOOGLE_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.5-flash-lite-preview-06-17"
    GEMINI_FALLBACK_MODEL: str = "models/gemma-3-27b-it"
    GEMINI_TEMPERATURE: float = 0.7
    GEMINI_MAX_TOKENS: int = 2048
    
    # Redis
    REDIS_URL: Optional[str] = None           # e.g. redis://localhost:6379/0 — leave empty to use in-memory fallback

    # Research Tools
    USE_MOCK_DATA: bool = True
    LINKEDIN_API_KEY: Optional[str] = None
    NEWS_API_KEY: Optional[str] = None
    CRM_DATABASE_URL: Optional[str] = None
    
    # Validation
    MIN_QUALITY_SCORE: int = 80
    MAX_ITERATIONS: int = 3
    
    # Features
    ENABLE_HUMAN_REVIEW: bool = False
    # ENABLE_AUTO_SEND: not yet implemented — flag reserved for future use
    # ENABLE_LEARNING_LOOP: not yet implemented — flag reserved for future use

    # Gmail SMTP (free email sending)
    GMAIL_ADDRESS: Optional[str] = None
    GMAIL_APP_PASSWORD: Optional[str] = None

    # Unipile (LinkedIn sending)
    UNIPILE_API_KEY: Optional[str] = None
    UNIPILE_DSN: Optional[str] = None          # e.g. "api4.unipile.com:13465"
    UNIPILE_DEFAULT_ACCOUNT_ID: Optional[str] = None  # your connected LinkedIn account ID
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "app.log"
    
    def update_from_worker(self, worker_config: dict):
        """Update settings dynamically from the central Worker module."""
        key_mapping = {
            "MIN_QUALITY_SCORE": "MIN_QUALITY_SCORE",
            "ENABLE_HUMAN_REVIEW": "ENABLE_HUMAN_REVIEW",
        }
        for global_key, local_attr in key_mapping.items():
            if global_key in worker_config:
                val = worker_config[global_key]
                if hasattr(self, local_attr) and val is not None:
                    if isinstance(getattr(self, local_attr), int):
                        try:
                            val = int(val)
                        except ValueError:
                            pass
                    elif isinstance(getattr(self, local_attr), bool):
                        if isinstance(val, str):
                            val = val.lower() == 'true'
                        else:
                            val = bool(val)
                    setattr(self, local_attr, val)
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()