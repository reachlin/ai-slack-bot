from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    slack_bot_token: str
    slack_app_token: str

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str
    llm_model: str = "deepseek-chat"
    llm_timeout_s: float = 120.0

    system_prompt: str = (
        "You are a helpful assistant in Slack. Be concise. "
        "Format with Slack mrkdwn: *bold*, _italic_, `code`, ```blocks```."
    )
    max_context_tokens: int = 8000
    knowledge_dir: Path = Path("knowledge")
    log_level: str = "INFO"

    # --- overseer control -------------------------------------------------
    # Slack user ids allowed to drive the overseer, comma-separated. Empty
    # admits nobody: a misconfigured deploy must fail closed, and this repo is
    # public so the real ids live in .env.
    overseer_admin_ids: str = ""
    goldfinger_repo: Path = Path("~/dev/private/gold-finger").expanduser()
    overseer_python: Path = Path("~/anaconda3/envs/gold-finger/bin/python").expanduser()
    overseer_label: str = "com.goldfinger.overseer"
    # overseer_status.py reconciles against the live Schwab account, so it is
    # slow by nature; well under Slack's patience, well over a local script's.
    overseer_timeout_s: float = 240.0
    approval_ttl_s: float = 300.0
    # Schwab OAuth token the overseer reads at startup.
    overseer_token_path: Path = (
        Path("~/dev/private/gold-finger/schwab/schwab_token.json").expanduser()
    )
    max_token_bytes: int = 65536


settings = Settings()
