from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    rate_limit_per_minute: int = 100
    allowed_origins: str = "*"
    worker_poll_interval: int = 10
    ecommerce_enabled: bool = False
    worker_batched: bool = False
    retention_days: int = 0

    class Config:
        env_file = ".env"


settings = Settings()
