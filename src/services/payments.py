from urllib.parse import urlencode

def build_yoomoney_quickpay_link(
    *,
    receiver: str,
    amount: float,
    label: str,
    targets: str = "Подписка на бота",
    success_url: str | None = None,
    fail_url: str | None = None,
) -> str:
    """
    Формирует ссылку на форму оплаты Quickpay (платёж на кошелёк).
    Документация ЮMoney Quickpay: quickpay-form=donate|shop
    """
    params = {
        "receiver": receiver,
        "quickpay-form": "shop",
        "targets": targets,
        "paymentType": "AC",       # AC — банковские карты, PC — ЮMoney
        "sum": f"{amount:.2f}",
        "label": label,            # используем для связи оплаты с chat_id
    }
    if success_url:
        params["successURL"] = success_url
    if fail_url:
        params["need-fail-url"] = "true"
        params["failURL"] = fail_url

    return "https://yoomoney.ru/quickpay/confirm.xml?" + urlencode(params, encoding="utf-8")