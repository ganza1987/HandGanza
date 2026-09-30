"""
Envia el analisis diario de balonmano por Telegram, ahora corrido desde
GitHub Actions (ver .github/workflows/analisis-diario.yml y
run_analisis_diario.py) en vez de con el `while True` que habia aqui antes.

Ese bucle interno (asyncio.sleep(60) sin parar) mantenia la app de Render
despierta 24/7, igual que le paso a BaloncestoGanza y a FutGanza, y fue lo
que agoto las 750h/mes gratis compartidas entre las tres apps (ver memoria
del proyecto). Se quita aqui por el mismo motivo que alli: enviar el
mensaje solo necesita la API de Telegram, no que la app este despierta.
"""
import os
import asyncio
import logging
import httpx
from datetime import date, datetime, timezone
from analyzer import analyze_match
from bot_handler import send_message, split_message

logger = logging.getLogger(__name__)

CHAT_IDS_ENV    = os.getenv("NOTIFY_CHAT_IDS", "")
APIFOOTBALL_KEY = os.getenv("APIFOOTBALL_KEY", "888285a75737af52283245495c97c67a")
APIHANDBALL_URL = "https://v1.handball.api-sports.io"

# IDs REALES, comprobados contra la API el 2026-09-30 (la misma cuenta de
# api-sports.io que usa BaloncestoGanza tambien da acceso -- Free -- a
# balonmano). Los que habia antes eran todos incorrectos: el id=10, por
# ejemplo, no es ASOBAL sino la liga croata "Premijer liga". Verificado
# pidiendo /teams de cada id y comprobando que salen clubes reales de ese
# pais (Aalborg/GOG en Dinamarca, Elverum en Noruega, Kristianstad en
# Suecia...). "EHF Cup" (antes id=3) se quita: el id real (179) no tiene
# NINGUNA temporada con datos, ni pasadas ni actual -- la competicion
# parece descontinuada o fusionada con la EHF European League.
#
# OJO, esto NO arregla que el analisis diario pueda funcionar de verdad
# todavia: el plan Free de balonmano de esta cuenta SOLO da acceso a las
# temporadas 2022-2024 ("Free plans do not have access to this season, try
# from 2022 to 2024" -- error real de la API), no a la temporada en curso
# (2026). Sin subir de plan (Pro, 19$/mes, es lo que desbloqueo la
# temporada actual tambien para baloncesto -- ver api-sports.io/pricing),
# get_todays_games() de mas abajo fallara siempre para la temporada de
# hoy. Decision del usuario, no tecnica.
HANDBALL_LEAGUES = {
    131: "EHF Champions League",
    145: "EHF European League",
    103: "Liga ASOBAL (España)",
    39:  "Bundesliga (Alemania)",
    34:  "Starligue (Francia)",
    23:  "Liga danesa (Herre Handbold Ligaen)",
    75:  "Liga noruega (REMA 1000-ligaen)",
    113: "Liga sueca (Handbollsligan)",
}

def get_notify_chat_ids() -> list[str]:
    if not CHAT_IDS_ENV:
        return []
    return [c.strip() for c in CHAT_IDS_ENV.split(",") if c.strip()]


def temporada_actual_balonmano() -> int:
    """
    Temporada de balonmano en curso, como numero de ANO EN QUE EMPIEZA (las
    ligas europeas de balonmano -- ASOBAL, Bundesliga, Starligue, EHF...--
    arrancan en agosto/septiembre y terminan en primavera/verano siguiente,
    igual que Euroliga/Eurocup/NBL1 en baloncesto). Misma formula ya
    verificada contra la API real para esas ligas de baloncesto (ver
    basketball_api.temporada_actual en el repo BaloncestoGanza).

    OJO: para balonmano esto NO se ha podido verificar contra la API real
    todavia (la clave de prueba usada tenia la cuenta suspendida en
    api-football.com al escribir esto, 2026-09-27) -- antes de fiarse del
    todo del aviso automatico, comprobar que get_todays_games devuelve
    partidos reales de hoy con una clave que funcione.
    """
    hoy = date.today()
    return hoy.year if hoy.month >= 8 else hoy.year - 1


async def apih(endpoint: str, params: dict) -> dict:
    headers = {
        "x-apisports-key": APIFOOTBALL_KEY,
        "x-rapidapi-host": "v1.handball.api-sports.io",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{APIHANDBALL_URL}/{endpoint}", headers=headers, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning(f"apih({endpoint}): {e}")
        return {}

async def get_todays_games(league_id: int, season: int) -> list:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = await apih("games", {"league": league_id, "season": season, "date": today})
    return data.get("response", [])

async def send_daily_handball_analysis():
    chat_ids = get_notify_chat_ids()
    if not chat_ids:
        return

    season = temporada_actual_balonmano()
    all_games = []

    for league_id, league_name in HANDBALL_LEAGUES.items():
        games = await get_todays_games(league_id, season)
        for g in games:
            home = g["teams"]["home"]["name"]
            away = g["teams"]["away"]["name"]
            date_str = g.get("date", "")
            all_games.append({"home": home, "away": away, "league": league_name, "date": date_str})
        await asyncio.sleep(0.5)

    today_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    if not all_games:
        for chat_id in chat_ids:
            await send_message(chat_id,
                f"🤾 *Análisis diario — Balonmano*\n_No hay partidos hoy._")
        return

    for chat_id in chat_ids:
        await send_message(chat_id,
            f"🤾 *ANÁLISIS DIARIO — BALONMANO*\n"
            f"📅 {today_str} · {len(all_games)} partidos\n_Generando análisis..._")

    for i, g in enumerate(all_games, 1):
        try:
            report = await analyze_match(g["home"], g["away"])
            prefix = f"🏆 *{g['league']}*\n\n"
            for chat_id in chat_ids:
                for chunk in split_message(prefix + report):
                    await send_message(chat_id, chunk)
                    await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Error analizando {g['home']} vs {g['away']}: {e}")
        await asyncio.sleep(3)

    for chat_id in chat_ids:
        await send_message(chat_id,
            f"✅ *Balonmano — {len(all_games)} análisis completados*")
