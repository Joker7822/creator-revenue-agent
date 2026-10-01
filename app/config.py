from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    custom_api_base_url: str = "http://127.0.0.1:8000"
    custom_api_token: str = ""

    database_url: str = "sqlite:///./agent.db"

    min_creator_age: int = 18
    require_human_review: bool = True
    allow_auto_publish: bool = False


settings = Settings()
