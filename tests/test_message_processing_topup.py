import asyncio
from types import SimpleNamespace

from domain.models import UserProfile
from usecases.message_processing import MessageProcessor


class DummyLLM:
    async def reply(self, *, user_text: str, chat_id: int) -> str:
        return ""

    async def reply_with_image(
        self,
        *,
        chat_id: int,
        image_bytes: bytes,
        image_mime_type: str,
        user_text: str = "",
    ) -> str:
        return ""

    async def recommend_day(
        self,
        *,
        chat_id: int,
        summary: dict,
        profile: dict,
    ) -> str:
        return ""


class DummySessions:
    async def set_active(self, chat_id: int, active: bool) -> None:
        return None

    async def is_active(self, chat_id: int) -> bool:
        return True

    async def list_active(self):
        return []


class DummyNutrition:
    async def add_items(self, chat_id: int, items: list[dict]) -> None:
        return None

    async def get_log(self, chat_id: int) -> list[dict]:
        return []

    async def clear(self, chat_id: int) -> None:
        return None

    async def remove_last(self, chat_id: int) -> bool:
        return False

    async def remove_by_indices(self, chat_id: int, indices: set[int]) -> int:
        return 0


class DummyProfiles:
    def __init__(self, profile: UserProfile | None) -> None:
        self.profile = profile

    async def get(self, chat_id: int) -> UserProfile | None:
        return self.profile


def make_processor(profile: UserProfile | None) -> MessageProcessor:
    settings = SimpleNamespace(
        yoomoney_receiver="41001111222333",
        yoomoney_success_url="https://example.com/success",
        yoomoney_fail_url="https://example.com/fail",
        subscription_price=99.0,
        subscription_days=14,
    )
    return MessageProcessor(
        llm=DummyLLM(),
        sessions=DummySessions(),
        nutrition=DummyNutrition(),
        profiles=DummyProfiles(profile),
        settings=settings,
    )


def test_build_topup_pay_text_for_active_subscription_shows_extension_semantics():
    processor = make_processor(
        UserProfile(
            chat_id=1,
            name=None,
            username=None,
            calories_goal=None,
            height_cm=None,
            weight_kg=None,
            subscribe_until="2999-01-01",
            referals=0,
        )
    )

    text = asyncio.run(processor.build_topup_pay_text(1))

    assert "Докупить подписку" in text
    assert "2999-01-01" in text
    assert "добавятся после этой даты" in text


def test_build_topup_pay_text_without_active_subscription_acts_like_new_purchase():
    processor = make_processor(None)

    text = asyncio.run(processor.build_topup_pay_text(1))

    assert "Активной подписки сейчас нет" in text
    assert "sub_1_w7" in text
