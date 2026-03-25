from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings
from services.payments import build_yoomoney_quickpay_link


@dataclass(frozen=True)
class SubscriptionPlan:
    slug: str
    price_rub: float
    days: int
    title: str


# Актуальные тарифы в UI и для проверки суммы в webhook.
STANDARD_PLANS: tuple[SubscriptionPlan, ...] = (
    SubscriptionPlan(slug="w7", price_rub=50.0, days=7, title="Неделя"),
    SubscriptionPlan(slug="y365", price_rub=2500.0, days=365, title="Год"),
)

_PLANS_BY_SLUG = {p.slug: p for p in STANDARD_PLANS}


def parse_yoomoney_label(label: str) -> tuple[int, str | None] | None:
    """
    Форматы:
    - sub_<chat_id> — legacy, цена/дни из Settings
    - sub_<chat_id>_<slug> — slug из STANDARD_PLANS
    """
    if not label.startswith("sub_"):
        return None
    rest = label[4:]
    if not rest:
        return None
    if "_" not in rest:
        try:
            return int(rest), None
        except ValueError:
            return None
    chat_part, slug = rest.rsplit("_", 1)
    if not slug:
        return None
    try:
        chat_id = int(chat_part)
    except ValueError:
        return None
    return chat_id, slug


def resolve_plan_for_payment(slug: str | None, settings: Settings) -> tuple[float, int, str] | None:
    """
    Возвращает (price_rub, days, human_title) или None, если slug неизвестен
    (legacy: slug is None — берём из settings).
    """
    if slug is None:
        return (
            float(settings.subscription_price),
            int(settings.subscription_days),
            "Подписка",
        )
    plan = _PLANS_BY_SLUG.get(slug)
    if not plan:
        return None
    return plan.price_rub, plan.days, plan.title


def build_plan_payment_link(settings: Settings, chat_id: int, plan: SubscriptionPlan) -> str:
    label = f"sub_{chat_id}_{plan.slug}"
    return build_yoomoney_quickpay_link(
        receiver=settings.yoomoney_receiver or "",
        amount=plan.price_rub,
        label=label,
        targets=f"Подписка: {plan.title}",
        success_url=settings.yoomoney_success_url,
        fail_url=settings.yoomoney_fail_url,
    )


def _plan_offer_lines(settings: Settings, chat_id: int) -> list[str]:
    lines: list[str] = []
    for p in STANDARD_PLANS:
        link = build_plan_payment_link(settings, chat_id, p)
        lines.append(
            f"\n<b>{p.title}</b> — <b>{p.price_rub:.0f} ₽</b> ({p.days} дн.)\n{link}"
        )
    lines.append(
        "\nПосле оплаты дни подписки начислятся автоматически (обычно сразу после уведомления ЮMoney)."
    )
    return lines


def format_subscription_offer_text(settings: Settings, chat_id: int) -> str:
    lines = [
        "🔒 <b>Подписка закончилась</b>\n",
        "Выберите период и оплатите по ссылке:",
    ]
    lines.extend(_plan_offer_lines(settings, chat_id))
    return "\n".join(lines)


def format_subscription_topup_text(
    settings: Settings, chat_id: int, *, current_until: str | None
) -> str:
    """Текст для докупки/продления, пока подписка ещё активна (или без даты — как новая)."""
    if current_until:
        lines = [
            "📅 <b>Докупить подписку</b>\n",
            f"Сейчас доступ до: <b>{current_until}</b>.\n",
            "Оплаченные дни <b>добавятся после этой даты</b> (не пропадут).\n",
            "\nВыберите период и оплатите по ссылке:",
        ]
    else:
        lines = [
            "📅 <b>Оплата подписки</b>\n",
            "Активной подписки сейчас нет — после оплаты срок начнётся с сегодняшнего дня.\n",
            "\nВыберите период:",
        ]
    lines.extend(_plan_offer_lines(settings, chat_id))
    return "\n".join(lines)


def format_retry_payment_hints(settings: Settings, chat_id: int) -> str:
    """Короткий блок ссылок для повторной оплаты (ошибка суммы, codepro и т.д.)."""
    parts = []
    for p in STANDARD_PLANS:
        link = build_plan_payment_link(settings, chat_id, p)
        parts.append(f"• {p.title} ({p.price_rub:.0f} ₽): {link}")
    return "\n".join(parts)
