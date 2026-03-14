from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    telegram_chat_id: int = 0
    server_port: int = 8932
    permission_request_timeout: float = 5.0
    log_level: str = "INFO"
    db_path: str = "data/governance.db"
    rules_path: str = "rules.yaml"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
