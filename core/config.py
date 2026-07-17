"""
全局配置
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SQLite
    SQLITE_URL: str = "sqlite:///./data_outlook_v2.db"
    # JWT：必须由部署环境提供，不允许使用源码默认值。
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE: int = 30        # 分钟
    REFRESH_TOKEN_EXPIRE: int = 7 * 24 * 60  # 7天

    # 部署与安全基线
    CORS_ORIGINS: str = "http://localhost:8001,http://localhost:5173"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8001
    WORKFLOW_CODE_EXECUTION_ENABLED: bool = False
    SSRF_ALLOWED_PORTS: str = "80,443"
    SSRF_ALLOWED_HOSTS: str = ""
    SSRF_ALLOW_INTERNAL: bool = False

    # 初始化：默认关闭演示账号。生产首次启动必须显式提供管理员密码。
    ENABLE_DEMO_SEED: bool = False
    INITIAL_ADMIN_USERNAME: str = "admin"
    INITIAL_ADMIN_PASSWORD: str | None = None
    INITIAL_ADMIN_EMAIL: str = "admin@dataoutlook.cn"

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("SECRET_KEY 长度必须至少为 32 个字符")
        if value == "data_outlook_secret_2025_scu@@##":
            raise ValueError("SECRET_KEY 不得使用已公开的历史默认值")
        return value


config = AppConfig()
