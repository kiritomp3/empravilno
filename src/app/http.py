from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from app.container import build_container
from presentation.webhooks import yoomoney as yoomoney_webhook

def build_app() -> FastAPI:
    app = FastAPI(title="emgood http")
    app.include_router(yoomoney_webhook.router, prefix="/webhooks")

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

    return app

app = build_app()
