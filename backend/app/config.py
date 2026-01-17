"""Application configuration."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str

    # Redis
    redis_url: str

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    environment: str = "development"

    # Chess.com API
    chess_com_api_base_url: str = "https://api.chess.com/pub"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
