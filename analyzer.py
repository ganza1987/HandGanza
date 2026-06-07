import os
import httpx
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
APIFOOTBALL_KEY   = os.getenv("APIFOOTBALL_KEY", "888285a75737af52283245495c97c67a")
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
            return None
        for r in results:
            if name.lower() in r["name"].lower():
                return r
        return results[0]
    except Exception as e:
        logger.warning(f"find_team({name}): {e}")
        return None

async def get_fixtures(team_id: int, last: int = 12) -> list:
    try:
        data = await apih("games", {"team": team_id, "last": last})
        return data.get("response", [])
    except Exception as e:
        logger.warning(f"get_fixtures: {e}")
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

async def team_data(team_id: int) -> dict:
    fixes = await get_fixtures(team_id, 12)
    home_fixes = [f for f in fixes if f["teams"]["home"]["id"] == team_id and f["scores"]["home"] is not None]
    away_fixes = [f for f in fixes if f["teams"]["away"]["id"] == team_id and f["scores"]["home"] is not None]

    def calc(fix_list, is_home_loc):
        gf_l, ga_l, h1_l, h2_l = [], [], [], []
        results_fmt = []
        for fix in fix_list[:6]:
            is_h = fix["teams"]["home"]["id"] == team_id
            sh = fix["scores"]["home"] or 0
            sa = fix["scores"]["away"] or 0
            gf_l.append(sh if is_h else sa)
            ga_l.append(sa if is_h else sh)

            # Half time scores
            ht = fix.get("periods", {})
            h1_home = ht.get("first", {}).get("home")
            h1_away = ht.get("first", {}).get("away")
            if h1_home is not None and h1_away is not None:
                h1_l.append(h1_home + h1_away)

            fmt = fmt_result(fix, team_id)
            if fmt:
                results_fmt.append(fmt)

        return {
            "results": results_fmt[:5],
            "gf": avg(gf_l), "ga": avg(ga_l),
            "h1_avg": avg(h1_l),
            "fixes": fix_list[:5],
        }

    return {
        "home": calc(home_fixes, True),
        "away": calc(away_fixes, False),
    }

async def build_real_data(home_name: str, away_name: str) -> dict:
    ht = await find_team(home_name)
    at = await find_team(away_name)
    api_ok = ht is not None or at is not None

    result = {
        "home_team": ht, "away_team": at,
        "home_data": None, "away_data": None,
        "h2h": [], "api_ok": api_ok, "source": "API-Sports Handball"
    }

    if ht:
        result["home_data"] = await team_data(ht["id"])
    if at:
        result["away_data"] = await team_data(at["id"])
    if ht and at:
        result["h2h"] = await get_h2h(ht["id"], at["id"])

    if not api_ok:
        result["source"] = "Búsqueda web"
    return result

def nd(val):
    return str(val) if val is not None else None

def build_prompt(home: str, away: str, conditions: list[dict], data: dict) -> str:
    now = datetime.now().strftime("%d/%m/%Y")
    max_pts = sum(c["weight"] for c in conditions)
    hd = data.get("home_data") or {}
    ad = data.get("away_data") or {}

    blocks = [f"=== DATOS REALES BALONMANO ({now}) ===\n"]

    if data.get("home_data"):
        hn = data["home_team"]["name"]
        home_res = " ".join([fmt_result(f, data["home_team"]["id"]) for f in hd["home"]["fixes"] if fmt_result(f, data["home_team"]["id"])])
        away_res = " ".join([fmt_result(f, data["home_team"]["id"]) for f in hd["away"]["fixes"] if fmt_result(f, data["home_team"]["id"])])
        h1_str = f" | Media 1ªP: {nd(hd['home']['h1_avg'])}" if hd["home"].get("h1_avg") else ""
        blocks.append(
            f"🔵 {hn.upper()}\n"
            f"  Casa: {home_res} | Media goles: {nd(hd['home']['gf'])} marc / {nd(hd['home']['ga'])} enc{h1_str}\n"
            f"  Fuera: {away_res} | Media: {nd(hd['away']['gf'])} marc / {nd(hd['away']['ga'])} enc"
        )
    else:
        blocks.append(f"🔵 {home.upper()} — Sin datos en API")

    if data.get("away_data"):
        an = data["away_team"]["name"]
        home_res = " ".join([fmt_result(f, data["away_team"]["id"]) for f in ad["home"]["fixes"] if fmt_result(f, data["away_team"]["id"])])
        away_res = " ".join([fmt_result(f, data["away_team"]["id"]) for f in ad["away"]["fixes"] if fmt_result(f, data["away_team"]["id"])])
        h1_str = f" | Media 1ªP: {nd(ad['away']['h1_avg'])}" if ad["away"].get("h1_avg") else ""
        blocks.append(
            f"\n🔴 {an.upper()}\n"
            f"  Fuera: {away_res} | Media goles: {nd(ad['away']['gf'])} marc / {nd(ad['away']['ga'])} enc{h1_str}\n"
            f"  Casa: {home_res} | Media: {nd(ad['home']['gf'])} marc / {nd(ad['home']['ga'])} enc"
        )
    else:
        blocks.append(f"\n🔴 {away.upper()} — Sin datos en API")

    if data.get("h2h"):
        h2h_lines = []
        for fix in data["h2h"][:3]:
            d = fix["date"][:10] if fix.get("date") else "?"
            sh = fix["scores"]["home"]
            sa = fix["scores"]["away"]
            hn2 = fix["teams"]["home"]["name"][:8]
            an2 = fix["teams"]["away"]["name"][:8]
            h2h_lines.append(f"{d} {hn2} {sh}-{sa} {an2}")
        blocks.append("\n⚔️ H2H: " + " | ".join(h2h_lines))

    data_str = "\n".join(blocks)

    web_instruction = "" if data["api_ok"] else f"""
Sin datos en API. Usa web_search:
1. "sofascore {home} balonmano resultados 2026"
2. "sofascore {away} balonmano resultados 2026"
3. "{home} {away} balonmano head to head"
"""

    cond_list = "\n".join(f'• {c["label"]} (peso {c["weight"]})' for c in conditions)
    confidence = "⚠️ DATOS NO VERIFICADOS — " if not data["api_ok"] else ""

    return f"""Analista deportivo experto en balonmano. Análisis BREVE para Telegram. Máximo 1800 caracteres.

REGLA: USA SOLO los datos proporcionados. NUNCA inventes estadísticas.

{web_instruction}
DATOS:
{data_str}

CONDICIONES A EVALUAR:
{cond_list}

FORMATO EXACTO:

{confidence}🤾 *{home.upper()} vs {away.upper()}*
_[competición] · {now}_

🔵 *{home}* · [✅❌🟡 x5 casa]
Goles casa: X marc / X enc | Media 1ªP: X

🔴 *{away}* · [✅❌🟡 x5 fuera]
Goles fuera: X marc / X enc | Media 1ªP: X

⚔️ *H2H* · [últimos 3] · media total: X goles

━━━━━━━━━━━━━━━━
✅ *Condiciones*
[cada una: ✅/❌ Nombre — motivo breve]

📊 *X/{max_pts} pts · X%*
🟢 FAVORABLE / 🟡 DUDOSO / 🔴 NO RECOMENDABLE

🤾 [1 frase conclusión]
📡 _{data.get("source", "API-Sports")} · {now}_"""


async def analyze_match(home: str, away: str, conditions: list[dict] | None = None) -> str:
    if conditions is None:
        conditions = DEFAULT_CONDITIONS

    data = await build_real_data(home, away)
    logger.info(f"Handball API ok={data['api_ok']} for {home} vs {away}")

    prompt = build_prompt(home, away, conditions, data)

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 3000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
        "messages": [{"role": "user", "content": prompt}],
        "system": (
            "Eres un analista deportivo experto en balonmano. Respondes siempre en español. "
            "Usas SOLO los datos reales proporcionados. "
            "NUNCA inventas estadísticas ni porcentajes. "
            "Formato Markdown compatible con Telegram."
        ),
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(ANTHROPIC_URL, headers=headers, json=body)
            r.raise_for_status()
            data_r = r.json()
            text_parts = [
                block["text"]
                for block in data_r.get("content", [])
                if block.get("type") == "text"
            ]
            return "\n".join(text_parts) if text_parts else "❌ No se pudo generar el análisis."
    except httpx.HTTPStatusError as e:
        logger.error(f"Anthropic API error: {e.response.text}")
        return "❌ Error al generar el análisis."
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return "❌ Error inesperado."
