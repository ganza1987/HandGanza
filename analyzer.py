import os
import httpx
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
APIFOOTBALL_KEY   = os.getenv("APIFOOTBALL_KEY", "")
ANTHROPIC_URL     = "https://api.anthropic.com/v1/messages"
APIHANDBALL_URL   = "https://v1.handball.api-sports.io"

DEFAULT_CONDITIONS = [
    {"id": "over55",        "label": "Más de 55 goles totales en el partido",          "weight": 8},
    {"id": "over27_h1",     "label": "Más de 27 goles en la 1ª parte",                 "weight": 7},
    {"id": "home_form",     "label": "El local tiene mejor forma reciente",             "weight": 6},
    {"id": "away_goals",    "label": "Visitante promedia más de 27 goles/partido",      "weight": 5},
    {"id": "home_unbeaten", "label": "Local invicto en sus últimos 5",                  "weight": 6},
    {"id": "h2h_goals",     "label": "H2H: más de 55 goles de media",                  "weight": 5},
    {"id": "btts_h1",       "label": "Ambos equipos marcan más de 13 en 1ª parte",     "weight": 5},
    {"id": "home_goals",    "label": "Local promedia más de 28 goles en casa",          "weight": 5},
    {"id": "away_concede",  "label": "Visitante encaja más de 28 goles fuera",          "weight": 4},
    {"id": "over45",        "label": "Más de 45 goles totales en el partido",           "weight": 4},
]

# ── API-Sports Handball ───────────────────────────────────────────────────────

async def apih(endpoint: str, params: dict) -> dict:
    headers = {
        "x-apisports-key": APIFOOTBALL_KEY,
        "x-rapidapi-host": "v1.handball.api-sports.io",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{APIHANDBALL_URL}/{endpoint}", headers=headers, params=params)
        r.raise_for_status()
        return r.json()

async def find_team(name: str) -> dict | None:
    try:
        data = await apih("teams", {"search": name})
        results = data.get("response", [])
        if not results:
            print(f"[DEBUG] find_team({name}): 0 resultados")
            return None
        for r in results:
            if name.lower() in r["name"].lower():
                return r
        return results[0]
    except Exception as e:
        print(f"[DEBUG] find_team({name}) FALLO: {type(e).__name__}: {e}")
        return None

async def get_fixtures(team_id: int, last: int = 12) -> list:
    try:
        data = await apih("games", {"team": team_id, "last": last})
        return data.get("response", [])
    except Exception as e:
        print(f"[DEBUG] get_fixtures FALLO: {type(e).__name__}: {e}")
        return []

async def get_h2h(id1: int, id2: int) -> list:
    try:
        data = await apih("games/h2h", {"h2h": f"{id1}-{id2}", "last": 6})
        return data.get("response", [])
    except Exception as e:
        return []

def avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v)/len(v), 1) if v else None

def get_result(fix: dict, team_id: int) -> str:
    home_id = fix["teams"]["home"]["id"]
    sh = fix["scores"]["home"] or 0
    sa = fix["scores"]["away"] or 0
    is_home = home_id == team_id
    sf = sh if is_home else sa
    sc = sa if is_home else sh
    return "W" if sf > sc else "D" if sf == sc else "L"

def fmt_result(fix: dict, team_id: int) -> str:
    sh = fix["scores"]["home"]
    sa = fix["scores"]["away"]
    if sh is None:
        return None
    r = get_result(fix, team_id)
    is_home = fix["teams"]["home"]["id"] == team_id
    opp = fix["teams"]["away"]["name"] if is_home else fix["teams"]["home"]["name"]
    emoji = "✅" if r == "W" else "🟡" if r == "D" else "❌"
    return f"{emoji}{sh}-{sa} {opp[:7]}"

as