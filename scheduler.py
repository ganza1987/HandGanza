"""
Scheduler for handball bot.
Sends daily analysis for major handball leagues.
"""
import os
import asyncio
import logging
import httpx
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
from analyzer import analyze_match
from bot_handler import send_message, split_message

logger = logging.getLogger(__name__)

CHAT_IDS_ENV    = os.getenv("NOTIFY_CHAT_IDS", "")
APIFOOTBALL_KEY = os.getenv("APIFOOTBALL_KEY", "888285a75737af52283245495c97c67a")
APIHANDBALL_URL = "https://v1.handball.api-sports.io"

HANDBALL_LEAGUES = {
    1:   "EHF Champions League",
    2:   "EHF European League",
    3:   "EHF Cup",
    10:  "Liga ASOBAL (España)",
    11:  "Bundesliga (Alemania)",
    12:  "Starligue (Francia)",
    13:  "Liga danesa",
    14:  "Liga noruega",
    15:  "Liga sueca",
}

SEND_HOUR_SPAIN = 9  # 9:00 AM hora España

def get_notify_chat_ids() -> list[str]:
    if not CHAT_IDS_ENV:
        return []
    return [c.strip() for c in CHAT_IDS_ENV.split(",") if c.strip()]

def to_utc_hour(spain_hour: int) -> int:
    spain_tz = ZoneInfo("Europe/Madrid")
    today = date.today()
    spain_dt = datetime(today.year, today.month, today.day, spain_hour, 0, tzinfo=spain_tz)
    return spain_dt.astimezone(timezone.utc).hour

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

    season = datetime.now(timezone.utc).year
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

async def start_scheduler():
    logger.info("Handball scheduler started.")
    already_sent: set[str] = set()

    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            today_key = now_utc.strftime("%Y-%m-%d")
            key = f"handball_{today_key}"

            if now_utc.hour == to_utc_hour(SEND_HOUR_SPAIN) and now_utc.minute < 10:
                if key not in already_sent:
                    already_sent.add(key)
                    await send_daily_handball_analysis()
        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        await asyncio.sleep(60)
