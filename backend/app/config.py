import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./pfos.db"
    jwt_secret: str = "development-only-change-this"
    jwt_expire_minutes: int = 1440
    credential_encryption_key: str | None = None
    plaid_client_id: str | None = None
    plaid_secret: str | None = None
    plaid_environment: str = "sandbox"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    ollama_enabled: bool = Field(default=False, validation_alias="PFOS_OLLAMA_ENABLED")
    ollama_model: str | None = Field(default=None, validation_alias="PFOS_OLLAMA_MODEL")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings(_env_file=None) if os.environ.get('PFOS_DESKTOP_RUNTIME') == '1' else Settings()
