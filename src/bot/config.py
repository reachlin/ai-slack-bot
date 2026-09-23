from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    slack_bot_token: str
    slack_app_token: str

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str
    llm_model: str = "deepseek-chat"

    system_prompt: str = (
        "You are a helpful assistant in Slack. Be concise. "
        "Format with Slack mrkdwn: *bold*, _italic_, `code`, ```blocks```."
    )
    max_context_tokens: int = 8000
    log_level: str = "INFO"


settings = Settings()
