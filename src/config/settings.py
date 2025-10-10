from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    yoomoney_receiver: str | None = None        # номер кошелька ЮMoney (4100...)
    yoomoney_secret: str | None = None          # notification_secret из настроек формы
    yoomoney_success_url: str | None = None     # страница "успех" (можно t.me/<bot>?start=success)
    yoomoney_fail_url: str | None = None        # "ошибка/отмена"
    subscription_price: float = 10           # цена подписки за период
    subscription_days: int = 30   