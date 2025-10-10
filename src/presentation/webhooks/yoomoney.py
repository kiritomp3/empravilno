from __future__ import annotations
import hashlib
from urllib.parse import quote_plus

from fastapi import APIRouter, Request, HTTPException
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from app.container import build_container

router = APIRouter()


def _check_signature(form: dict[str, str], secret: str) -> bool:
    parts = [
        form.get("notification_type", ""),
        form.get("operation_id", ""),
        form.get("amount", ""),
        form.get("currency", ""),
        form.get("datetime", ""),
        form.get("sender", ""),
        form.get("codepro", ""),
        secret or "",
        form.get("label", ""),
    ]
    line = "&".join(parts)
    sha = hashlib.sha1(line.encode("utf-8")).hexdigest()
    return sha == (form.get("sha1_hash") or "").lower()


def _payment_link(s, chat_id: int) -> str:
    label = f"sub_{chat_id}"
    targets = quote_plus("Подписка на бота")
    return (
        f"https://yoomoney.ru/quickpay/confirm?"
        f"receiver={s.yoomoney_receiver}"
        f"&quickpay-form=shop"
        f"&paymentType=AC"
        f"&sum={float(s.subscription_price):.2f}"
        f"&label={label}"
        f"&targets={targets}"
        f"&successURL={quote_plus(s.yoomoney_success_url)}"
        f"&failURL={quote_plus(s.yoomoney_fail_url)}"
    )


from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError

async def _notify(chat_id: int, text: str, token: str):
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    try:
        me = await bot.get_me()
        print(f"[notify] using bot @{me.username} ({me.id}) to send -> {chat_id}")
        msg = await bot.send_message(chat_id, text)
        print(f"[notify] sent message_id={msg.message_id} to chat_id={chat_id}")
    except TelegramForbiddenError as e:
        # бот заблокирован пользователем, или нет разрешения писать в чат
        print(f"[notify] FORBIDDEN for chat_id={chat_id}: {repr(e)}")
    except TelegramBadRequest as e:
        # неверный chat_id, бот не в чате, формат HTML сломан и т.п.
        print(f"[notify] BAD_REQUEST for chat_id={chat_id}: {repr(e)}")
    except TelegramNetworkError as e:
        print(f"[notify] NETWORK error: {repr(e)}")
    except Exception as e:
        print(f"[notify] UNKNOWN send error: {repr(e)}")
    finally:
        await bot.session.close()

@router.post("/yoomoney/notify")
async def yoomoney_notify(request: Request):
    container = build_container()
    s = container.settings

    form = dict(await request.form())
    safe = {k: v for k, v in form.items() if k != "sha1_hash"}
    print("[yoomoney] notify:", safe)

    # 0) базовая валидация
    if not getattr(s, "yoomoney_secret", None):
        print("[yoomoney] missing yoomoney_secret in settings")
        raise HTTPException(status_code=400, detail="missing secret")

    if not _check_signature(form, s.yoomoney_secret):
        print("[yoomoney] bad signature")
        raise HTTPException(status_code=400, detail="bad signature")

    # --- проверяем тип нотификации ---
    nt = (form.get("notification_type") or "").lower()
    if nt not in ("p2p-incoming", "card-incoming"):
        print("[yoomoney] skip notification_type:", nt)
        return {"ok": True}

    label = form.get("label") or ""
    if not label.startswith("sub_"):
        print("[yoomoney] skip label:", label)
        return {"ok": True}

    try:
        chat_id = int(label.split("_", 1)[1])
    except Exception:
        print("[yoomoney] bad label:", label)
        return {"ok": True}

    # 1) codepro
    if (form.get("codepro") or "false").lower() == "true":
        txt = (
            "⚠️ <b>Платёж в обработке</b>\n\n"
            "ЮMoney прислал платеж с кодом протекции (codepro). "
            "Автозачисление недоступно, дождитесь подтверждения или попробуйте оплатить картой без протекции.\n\n"
            f"Повторить оплату: { _payment_link(s, chat_id) }"
        )
        await _notify(chat_id, txt, s.bot_token)
        return {"ok": True}

    # Сумма
    amount_str = (form.get("withdraw_amount") or form.get("amount") or "0").replace(",", ".")
    try:
        amount = float(amount_str)
    except Exception:
        amount = 0.0

    price = float(s.subscription_price)
    if amount + 1e-9 < price:
        txt = (
            "⚠️ <b>Оплата не зачислена</b>\n\n"
            f"Получено: <b>{amount:.2f} ₽</b>, требуется: <b>{price:.2f} ₽</b>.\n"
            "Если это ошибка — попробуйте оплатить ещё раз по ссылке:\n"
            f"{ _payment_link(s, chat_id) }"
        )
        print(f"[yoomoney] amount too small: got={amount} need={price}")
        await _notify(chat_id, txt, s.bot_token)
        return {"ok": True}

    # 2) идемпотентность
    op_id = form.get("operation_id") or ""
    try:
        r = getattr(container, "redis", None) or getattr(container.processor._profiles, "_r", None)
        if r:
            if await r.sismember("ym:ops", op_id):
                print("[yoomoney] duplicate operation:", op_id)
                return {"ok": True}
            await r.sadd("ym:ops", op_id)
    except Exception as e:
        print("[yoomoney] idempotency warn:", repr(e))

    # 3) начисляем дни
    try:
        added = int(s.subscription_days)
        new_until = await container.processor._profiles.extend_subscription(chat_id, added)
    except Exception as e:
        print("[yoomoney] increment error:", repr(e))
        txt = (
            "❗️ <b>Оплата прошла, но дни не зачислены автоматически</b>\n\n"
            "Я уже вижу платеж, но не смог обновить профиль.\n"
            "Напишите, пожалуйста, в поддержку — мы всё поправим вручную."
        )
        await _notify(chat_id, txt, s.bot_token)
        return {"ok": True}

    # 4) успех
    txt = (
        "✅ <b>Оплата прошла</b>\n\n"
        f"Мы начислили <b>{int(s.subscription_days)}</b> дней подписки.\n"
        f"Подписка действует до: <b>{new_until}</b>.\n"
        "Спасибо за поддержку!"
    )
    await _notify(chat_id, txt, s.bot_token)

    print(f"[yoomoney] days +{s.subscription_days} to chat {chat_id}")
    return {"ok": True}