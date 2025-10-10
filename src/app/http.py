from fastapi import FastAPI
from presentation.webhooks import yoomoney as yoomoney_webhook

def build_app() -> FastAPI:
    app = FastAPI(title="emgood http")
    app.include_router(yoomoney_webhook.router, prefix="/webhooks")
    return app

app = build_app()