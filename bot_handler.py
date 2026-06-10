import os
import re
import logging
import httpx
from analyzer import analyze_match, apih
from bet_handler import handle_bet_command
from image_bet_handler import process_bet_screenshot

logger = logging.getLogger(__name__)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_HANDBALL", "")
TELEGRAM_API   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

VS_PATTERN = re.compile(
    r"^(.+?)\s+(?:vs\.?|versus|contra|-)\s+(.+)$",
    re.IGNORECASE | re.UNICODE
)

async def send_message(chat_id, text: str, parse_mode: str = "Markdown"):
    async with httpx.AsyncClient(timeout=30) as client:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        if r.status_code != 200:
            logger.error(f"Telegram error: {r.text}")

async def send_typing(chat_id):
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{TELEGRAM_API}/sendChatAction",
                         json={"chat_id": chat_id, "action": "typing"})

def split_message(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks

async def handle_update(data: dict):
    message = data.get("message") or data.get("edited_message")
    if not message:
        return
    chat_id = message["chat"]["id"]

    if message.get("photo"):
        photo = message["photo"][-1]
        await send_typing(chat_id)
        await process_bet_screenshot(chat_id, photo["file_id"], message.get("caption", ""), send_message)
        return

    text = message.get("text", "").strip()
    if not text:
        return

    if text.startswith("/start") or text.startswith("/help"):
        await send_message(chat_id, HELP_TEXT)
        return

    # Trigger manual del análisis diario
    if text.lower().startswith("/handball"):
        await send_message(chat_id,
            "🤾 *Lanzando análisis diario de balonmano...*\n_Esto puede tardar varios minutos._")
        from scheduler import send_daily_handball_analysis
        await send_daily_handball_analysis()
        return

    # Lista de ligas disponibles en la API
    if text.lower().startswith("/ligas"):
        await send_typing(chat_id)
        try:
            data = await apih("leagues", {"season": 2026})
            leagues = data.get("response", [])
            if not leagues:
                await send_message(chat_id, "❌ No se pudieron obtener las ligas.")
                return
            lines = ["🏆 *Ligas disponibles en API-Sports Handball*\n"]
            for lg in sorted(leagues, key=lambda x: x["id"]):
                country = lg.get("country", {}).get("name", "")
                name = lg.get("name", "")
                lid = lg.get("id", "")
                lines.append(f"`{lid}` — {name} ({country})")
            for chunk in split_message("\n".join(lines)):
                await send_message(chat_id, chunk)
        except Exception as e:
            logger.error(f"/ligas error: {e}")
            await send_message(chat_id, "❌ Error al obtener las ligas.")
        return

    handled = await handle_bet_command(chat_id, text, send_message)
    if handled:
        return

    match = VS_PATTERN.match(text)
    if match:
        home = match.group(1).strip()
        away = match.group(2).strip()
        await send_typing(chat_id)
        await send_message(chat_id,
            f"🤾 Analizando *{home}* vs *{away}*...\n_Esto puede tardar unos segundos._")
        await send_typing(chat_id)
        report = await analyze_match(home, away)
        for chunk in split_message(report):
            await send_message(chat_id, chunk)
        return

    await send_message(chat_id,
        "No reconozco ese formato.\n"
        "Escribe el partido así: `Barcelona vs Kiel`\n"
        "O usa /help para ver todos los comandos.")

HELP_TEXT = """
🤾 *HandGanza Bot — Análisis de Balonmano*

*Análisis de partidos:*
Escribe el partido: `Barcelona vs THW Kiel`

*Comandos:*
/handball — lanza el análisis de hoy
/ligas — ligas disponibles en la API

*Apuestas:*
📸 Envía una captura de tu apuesta
`/apuesta Partido ; Mercado ; Cuota ; Importe`
`/resultado <id> ganó|perdió|nula`
`/apuestas` — últimas apuestas
`/stats` — tus estadísticas
/web — dashboard web
/help — esta ayuda
""".strip()
