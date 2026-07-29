from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./pfos.db"
    jwt_secret: str = "development-only-change-this"
    jwt_expire_minutes: int = 1440
    credential_encryption_key: str | None = None
    plaid_client_id: str | None = None
    plaid_secret: str | None = None
    plaid_environment: str = "sandbox"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
