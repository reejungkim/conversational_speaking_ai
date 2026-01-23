"""
FastAPI Backend Configuration
Environment variables and settings management
"""
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # App
    app_name: str = "AI Language Tutor API"
    debug: bool = False
    
    # Supabase
    supabase_url: str
    supabase_key: str
    
    # OpenAI
    openai_api_key: str
    
    # Google Cloud
    google_credentials_path: Optional[str] = None
    google_credentials_json: Optional[str] = None
    
    # JWT
    jwt_secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60 * 24 * 7  # 7 days
    
    # OAuth Providers (Kakao, Naver)
    kakao_client_id: Optional[str] = None
    kakao_client_secret: Optional[str] = None
    kakao_redirect_uri: Optional[str] = None
    
    naver_client_id: Optional[str] = None
    naver_client_secret: Optional[str] = None
    naver_redirect_uri: Optional[str] = None
    
    # CORS
    cors_origins: str = "*"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()
