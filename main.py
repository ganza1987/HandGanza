import os
import logging
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
import httpx
from bot_handler import handle_update
from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_HANDBALL", "")
WEBHOOK_URL    = os.getenv("WEBHOOK_URL_HANDBALL", "")

async def set_webhook():
    if not TELEGRAM_TOKEN or not WEBHOOK_URL:
        return
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
            json={"url": f"{WEBHOOK_URL}/webhook"}
        )
        logger.info(f"Webhook set: {r.json()}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # El analisis diario ya no se envia desde aqui (ver scheduler.py):
    # el bucle interno que habia mantenia la app despierta 24/7 y gastaba
    # las horas gratis de Render. Ahora lo dispara GitHub Actions -- ver
    # .github/workflows/analisis-diario.yml y run_analisis_diario.py.
    init_db()
    await set_webhook()
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "HandGanza Bot running 🤾"}

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    await handle_update(data)
    return {"ok": True}
