from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from services.subscription_plans import (
    build_plan_payment_link,
    format_subscription_choice_text,
    format_subscription_expired_text,
    format_subscription_offer_text,
    format_subscription_topup_text,
    get_subscription_plans,
    parse_yoomoney_label,
    resolve_plan_for_payment,
)


def make_settings():
    return SimpleNamespace(
        yoomoney_receiver="41001111222333",
        yoomoney_success_url="https://example.com/success",
        yoomoney_fail_url="https://example.com/fail",
        subscription_price=99.0,
        subscription_days=14,
    )


def test_parse_yoomoney_label_supports_legacy_and_plan_labels():
    assert parse_yoomoney_label("sub_12345") == (12345, None)
    assert parse_yoomoney_label("sub_12345_w7") == (12345, "w7")
    assert parse_yoomoney_label("sub_12345_y365") == (12345, "y365")
    assert parse_yoomoney_label("order_12345") is None
    assert parse_yoomoney_label("sub_bad_w7") is None


def test_resolve_plan_for_payment_uses_settings_for_legacy_labels():
    settings = make_settings()

    assert resolve_plan_for_payment(None, settings) == (99.0, 14, "Подписка")
    assert resolve_plan_for_payment("w7", settings) == (50.0, 7, "Неделя")
    assert resolve_plan_for_payment("m30", settings) == (99.0, 14, "Месяц")
    assert resolve_plan_for_payment("y365", settings) == (1500.0, 365, "Год")
    assert resolve_plan_for_payment("missing", settings) is None


def test_build_plan_payment_link_contains_plan_specific_label_and_amount():
    settings = make_settings()
    week_plan = get_subscription_plans(settings)[0]

    link = build_plan_payment_link(settings, 777, week_plan)
    query = parse_qs(urlparse(link).query)

    assert query["receiver"] == ["41001111222333"]
    assert query["sum"] == ["50.00"]
    assert query["label"] == ["sub_777_w7"]
    assert query["targets"] == ["Подписка: Неделя"]


def test_subscription_offer_text_lists_all_standard_plans():
    settings = make_settings()

    text = format_subscription_offer_text(settings, 555)

    assert "Подписка закончилась" in text
    assert "Неделя" in text
    assert "Месяц" in text
    assert "Год" in text
    assert "sub_555_w7" in text
    assert "sub_555_m30" in text
    assert "sub_555_y365" in text


def test_subscription_expired_text_redirects_to_subscription_section():
    text = format_subscription_expired_text()

    assert "Подписка закончилась" in text
    assert 'Оплатить можно в разделе "Подписка"' in text
    assert "sub_" not in text


def test_subscription_topup_text_mentions_current_expiration_when_present():
    settings = make_settings()

    text = format_subscription_topup_text(settings, 555, current_until="2026-04-10")

    assert "Докупить подписку" in text
    assert "2026-04-10" in text
    assert "добавятся после этой даты" in text


def test_subscription_choice_text_mentions_current_until_for_active_subscription():
    text = format_subscription_choice_text(current_until="2026-04-10")

    assert "2026-04-10" in text
    assert "Выберите тариф" in text
    assert "добавятся после текущей даты" in text


def test_get_subscription_plans_uses_settings_for_month_plan():
    settings = make_settings()

    plans = get_subscription_plans(settings)

    assert [plan.slug for plan in plans] == ["w7", "m30", "y365"]
    assert plans[1].price_rub == 99.0
    assert plans[1].days == 14
