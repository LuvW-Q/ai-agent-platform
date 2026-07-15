"""
全局配置
"""
from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    # SQLite
    SQLITE_URL: str = "sqlite:///./data_outlook_v2.db"
    # JWT
    SECRET_KEY: str = "data_outlook_secret_2025_scu@@##"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE: int = 30        # 分钟
    REFRESH_TOKEN_EXPIRE: int = 7 * 24 * 60  # 7天


config = AppConfig()
