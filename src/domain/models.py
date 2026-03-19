from dataclasses import dataclass, field
from typing import Optional

@dataclass(frozen=True)
class ChatSession:
    chat_id: int
    active: bool

@dataclass
class UserProfile:
    chat_id: int
    name: str | None
    username: str | None
    calories_goal: int | None
    height_cm: int | None
    weight_kg: float | None
    subscribe_until: Optional[str]
    referals: int
    referral_usernames: list[str] = field(default_factory=list)
