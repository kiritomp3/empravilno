from __future__ import annotations
import hashlib

from fastapi import APIRouter, Request, HTTPException
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from app.container import build_container
import redis.asyncio as redis
from services.subscription_plans import (
    format_retry_payment_hints,
    parse_yoomoney_label,
    resolve_plan_for_payment,
)

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


from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError

IDEMPOTENCY_TTL_SECONDS = 90 * 24 * 60 * 60
PROCESSING_TTL_SECONDS = 15 * 60


async def _reserve_operation(r: redis.Redis, op_id: str) -> str:
    key = f"ym:op:{op_id}"
    current = await r.get(key)
    if current == "done":
        return "done"
    if current == "processing":
        return "processing"

    locked = await r.set(key, "processing", ex=PROCESSING_TTL_SECONDS, nx=True)
    if locked:
        return "reserved"

    current = await r.get(key)
    if current == "done":
        return "done"
    return "processing"


async def _mark_operation_done(r: redis.Redis, op_id: str) -> None:
    await r.set(f"ym:op:{op_id}", "done", ex=IDEMPOTENCY_TTL_SECONDS)


async def _release_operation(r: redis.Redis, op_id: str) -> None:
    await r.delete(f"ym:op:{op_id}")

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
    telemetry = container.telemetry

    form = dict(await request.form())
    safe = {k: v for k, v in form.items() if k != "sha1_hash"}
    print("[yoomoney] notify:", safe)
    await telemetry.incr("payments.webhook_total")

    # 0) базовая валидация
    if not getattr(s, "yoomoney_secret", None):
        print("[yoomoney] missing yoomoney_secret in settings")
        raise HTTPException(status_code=400, detail="missing secret")

    if not _check_signature(form, s.yoomoney_secret):
        print("[yoomoney] bad signature")
        await telemetry.incr("payments.bad_signature_total")
        raise HTTPException(status_code=400, detail="bad signature")

    # --- проверяем тип нотификации ---
    nt = (form.get("notification_type") or "").lower()
    if nt not in ("p2p-incoming", "card-incoming"):
        print("[yoomoney] skip notification_type:", nt)
        await telemetry.incr("payments.skipped_total")
        return {"ok": True}

    label = form.get("label") or ""
    parsed = parse_yoomoney_label(label)
    if not parsed:
        if label.startswith("sub_"):
            print("[yoomoney] bad label:", label)
        else:
            print("[yoomoney] skip label:", label)
        return {"ok": True}

    chat_id, plan_slug = parsed
    plan_resolved = resolve_plan_for_payment(plan_slug, s)
    if plan_resolved is None:
        print("[yoomoney] unknown plan in label:", label)
        return {"ok": True}

    price, subscription_days, plan_title = plan_resolved

    receiver = (form.get("receiver") or "").strip()
    if receiver and s.yoomoney_receiver and receiver != s.yoomoney_receiver:
        print(f"[yoomoney] unexpected receiver: {receiver}")
        await telemetry.incr("payments.rejected_total")
        raise HTTPException(status_code=400, detail="bad receiver")

    currency = (form.get("currency") or "").strip()
    if currency and currency != "643":
        print(f"[yoomoney] unexpected currency: {currency}")
        await telemetry.incr("payments.rejected_total")
        raise HTTPException(status_code=400, detail="bad currency")

    # 1) codepro
    if (form.get("codepro") or "false").lower() == "true":
        await telemetry.incr("payments.codepro_total")
        retry = format_retry_payment_hints(s, chat_id)
        txt = (
            "⚠️ <b>Платёж в обработке</b>\n\n"
            "ЮMoney прислал платеж с кодом протекции (codepro). "
            "Автозачисление недоступно, дождитесь подтверждения или попробуйте оплатить картой без протекции.\n\n"
            f"Повторить оплату:\n{retry}"
        )
        await _notify(chat_id, txt, s.bot_token)
        return {"ok": True}

    # Сумма
    amount_str = (form.get("withdraw_amount") or form.get("amount") or "0").replace(",", ".")
    try:
        amount = float(amount_str)
    except Exception:
        amount = 0.0

    if amount + 1e-9 < price:
        await telemetry.incr("payments.failed_total")
        retry = format_retry_payment_hints(s, chat_id)
        txt = (
            "⚠️ <b>Оплата не зачислена</b>\n\n"
            f"Получено: <b>{amount:.2f} ₽</b>, требуется: <b>{price:.2f} ₽</b>.\n"
            "Если это ошибка — попробуйте оплатить ещё раз:\n"
            f"{retry}"
        )
        print(f"[yoomoney] amount too small: got={amount} need={price}")
        await _notify(chat_id, txt, s.bot_token)
        return {"ok": True}

    # 2) идемпотентность
    op_id = form.get("operation_id") or ""
    if not op_id:
        print("[yoomoney] missing operation_id")
        raise HTTPException(status_code=400, detail="missing operation_id")

    r = getattr(container, "redis", None) or getattr(container.processor._profiles, "_r", None)
    if not r:
        print("[yoomoney] redis unavailable for idempotency")
        raise HTTPException(status_code=503, detail="storage unavailable")

    try:
        reservation = await _reserve_operation(r, op_id)
        if reservation == "done":
            print("[yoomoney] duplicate operation:", op_id)
            await telemetry.incr("payments.duplicate_total")
            return {"ok": True}
        if reservation == "processing":
            print("[yoomoney] operation still processing:", op_id)
            await telemetry.incr("payments.processing_conflict_total")
            raise HTTPException(status_code=409, detail="operation in progress")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        print("[yoomoney] idempotency error:", repr(e))
        raise HTTPException(status_code=503, detail="storage unavailable")

    # 3) начисляем дни
    try:
        added = int(subscription_days)
        new_until = await container.processor._profiles.extend_subscription(chat_id, added)
    except Exception as e:
        print("[yoomoney] increment error:", repr(e))
        await _release_operation(r, op_id)
        await telemetry.incr("payments.credit_error_total")
        txt = (
            "❗️ <b>Оплата прошла, но дни не зачислены автоматически</b>\n\n"
            "Я уже вижу платеж, но не смог обновить профиль.\n"
            "Напишите, пожалуйста, в поддержку — мы всё поправим вручную."
        )
        await _notify(chat_id, txt, s.bot_token)
        return {"ok": True}

    await _mark_operation_done(r, op_id)
    await telemetry.incr("payments.success_total")
    await telemetry.incr_float("payments.revenue_rub_total", amount)
    await telemetry.set_text("payments.last_success_chat_id", str(chat_id))
    await telemetry.set_text("payments.last_operation_id", op_id)

    # 4) успех
    txt = (
        "✅ <b>Оплата прошла</b>\n\n"
        f"Тариф: <b>{plan_title}</b>. Начислено <b>{int(subscription_days)}</b> дней.\n"
        f"Подписка действует до: <b>{new_until}</b>.\n"
        "Спасибо за поддержку!"
    )
    await _notify(chat_id, txt, s.bot_token)

    print(f"[yoomoney] days +{subscription_days} to chat {chat_id} ({plan_title})")
    return {"ok": True}
