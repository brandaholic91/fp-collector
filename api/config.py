from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    rate_limit_per_minute: int = 100
    allowed_origins: str = "*"

    class Config:
        env_file = ".env"


settings = Settings()
