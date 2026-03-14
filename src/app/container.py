# src/app/container.py
from __future__ import annotations
from typing import Optional
from config.settings import Settings
from services.openai_client import OpenAIConfig, OpenAILLMClient
from infrastructure.memory_store import InMemoryChatSessionStore
from infrastructure.redis_store import RedisChatSessionStore
from infrastructure.redis_store import RedisNutritionLogStore
from infrastructure.redis_store import RedisUserProfileStore
from infrastructure.telemetry import RedisTelemetry
from usecases.message_processing import MessageProcessor

class Container:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = OpenAILLMClient(
            OpenAIConfig(api_key=settings.openai_api_key, model=settings.openai_model)
        )
        self.sessions = (
            RedisChatSessionStore(settings.redis_url)
            if settings.redis_url else
            InMemoryChatSessionStore()
        )
        self.nutrition = (
            RedisNutritionLogStore(settings.redis_url)
        )

        self.profiles = RedisUserProfileStore(settings.redis_url)
        self.telemetry = RedisTelemetry(settings.redis_url)

        self.processor = MessageProcessor(self.llm, self.sessions, self.nutrition, self.profiles, settings=self.settings)

def build_container(settings: Optional[Settings] = None) -> Container:
    return Container(settings or Settings())
