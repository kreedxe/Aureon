from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    session_token: SecretStr

    model_config = SettingsConfigDict(env_prefix="AUREON_", extra="ignore")


settings = Settings()
