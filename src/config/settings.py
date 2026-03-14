from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field

class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    admin_token: str | None = Field(default=None, alias="ADMIN_TOKEN")
    admin_chat_ids_raw: str = Field(default="", alias="ADMIN_CHAT_IDS")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    yoomoney_receiver: str | None = Field(
        default=None,
        validation_alias=AliasChoices("YOOMONEY_RECEIVER", "yoomoney_receiver"),
    )
    yoomoney_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("YOOMONEY_SECRET", "yoomoney_secret"),
    )
    yoomoney_success_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("YOOMONEY_SUCCESS_URL", "yoomoney_success_url"),
    )
    yoomoney_fail_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("YOOMONEY_FAIL_URL", "yoomoney_fail_url"),
    )
    subscription_price: float = Field(
        default=10,
        validation_alias=AliasChoices("SUBSCRIPTION_PRICE", "subscription_price"),
    )
    subscription_days: int = Field(
        default=30,
        validation_alias=AliasChoices("SUBSCRIPTION_DAYS", "subscription_days"),
    )

    @property
    def admin_chat_ids(self) -> set[int]:
        values: set[int] = set()
        for chunk in self.admin_chat_ids_raw.split(","):
            item = chunk.strip()
            if not item:
                continue
            try:
                values.add(int(item))
            except ValueError:
                continue
        return values
