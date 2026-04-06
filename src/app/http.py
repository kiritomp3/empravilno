import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import unquote, parse_qsl

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from app.container import build_container
from presentation.webhooks import yoomoney as yoomoney_webhook

MINIAPP_HTML = Path(__file__).resolve().parents[2] / "miniapp" / "index_test.html"


def _verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Проверяет подпись Telegram WebApp initData.
    Возвращает распарсенный словарь или None если подпись неверна.
    """
    params = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = params.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    return params


def build_app() -> FastAPI:
    app = FastAPI(title="emgood http")
    app.include_router(yoomoney_webhook.router, prefix="/webhooks")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        container = build_container()
        if not await container.telemetry.ping():
            raise HTTPException(status_code=503, detail="redis unavailable")
        return {"status": "ready"}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> str:
        container = build_container()
        return await container.telemetry.render_prometheus()

    @app.get("/stats")
    async def stats(x_admin_token: str | None = Header(default=None)) -> dict[str, object]:
        container = build_container()
        expected = container.settings.admin_token
        if not expected or x_admin_token != expected:
            raise HTTPException(status_code=403, detail="forbidden")
        return await container.telemetry.collect_all_stats()

    @app.get("/miniapp", response_class=FileResponse)
    async def miniapp() -> FileResponse:
        if not MINIAPP_HTML.exists():
            raise HTTPException(status_code=404, detail="mini app unavailable")
        return FileResponse(MINIAPP_HTML)

    @app.get("/miniapp/streak")
    async def miniapp_streak(
        init_data: str = Query(..., description="Telegram WebApp initData string"),
    ) -> dict:
        """
        Возвращает streak-данные для Mini App.
        Принимает initData из Telegram WebApp, проверяет подпись HMAC.
        """
        container = build_container()
        bot_token = container.settings.bot_token

        parsed = _verify_telegram_init_data(init_data, bot_token)
        if parsed is None:
            raise HTTPException(status_code=403, detail="invalid initData signature")

        try:
            user_obj = json.loads(parsed.get("user", "{}"))
            chat_id = int(user_obj["id"])
        except (KeyError, ValueError, TypeError):
            raise HTTPException(status_code=400, detail="cannot extract user id from initData")

        stats = await container.streak.get_stats(chat_id)
        return stats

    return app


app = build_app()
