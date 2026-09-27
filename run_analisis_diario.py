"""
Analisis diario de balonmano (partidos de hoy en las ligas seguidas) por
Telegram, corrido desde GitHub Actions (ver
.github/workflows/analisis-diario.yml) en vez del `while True` que habia en
scheduler.py -- mismo motivo que en BaloncestoGanza y FutGanza: enviar el
mensaje solo necesita la API de Telegram, no que la app de Render este
despierta, y ese bucle era lo que agotaba las 750h/mes gratis compartidas
entre las tres apps.

Envio a prueba de retrasos, igual que los otros dos proyectos: GitHub
Actions retrasa a veces los cron programados varias horas y alguna vez no
los dispara ningun dia (visto en BaloncestoGanza el 2026-09-27: los 4
intentos de esa mañana no llegaron a ejecutarse). Por eso se acepta una
VENTANA ancha (9 a 18h en Madrid) en vez de exigir la hora exacta, y se
reserva "aviso de hoy" en la base de datos compartida con FutGanza (tabla
avisos_enviados, tipo="handball" para no chocar con los tipos de FutGanza)
para que el primero que llega envie y los demas no dupliquen.

Si Telegram rechaza algun envio o falta NOTIFY_CHAT_IDS, la ejecucion
termina en ROJO (GitHub avisa por correo) y la reserva se libera para
reintentar. Cada resultado se anota tambien como anotacion
(::notice::/::error::) visible en la pantalla resumen de la ejecucion.
FORZAR_ANALISIS=true (ejecucion manual via workflow_dispatch) se salta la
ventana y la reserva.
"""
import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import bot_handler
import database
import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TIPO_AVISO = "handball"
HORA_INICIO_MADRID = 9
HORA_FIN_MADRID = 18


def anotar(nivel: str, mensaje: str) -> None:
    """Anotacion de GitHub Actions: sale en la pantalla resumen de la ejecucion."""
    print(f"::{nivel}::{mensaje}", flush=True)


async def main():
    forzar = os.getenv("FORZAR_ANALISIS", "").strip().lower() == "true"
    ahora = datetime.now(ZoneInfo("Europe/Madrid"))

    if not forzar and not (HORA_INICIO_MADRID <= ahora.hour < HORA_FIN_MADRID):
        anotar("notice", f"Fuera de ventana ({ahora:%H:%M} en Madrid, va de {HORA_INICIO_MADRID} a {HORA_FIN_MADRID} h): no se hace nada.")
        return

    if not scheduler.get_notify_chat_ids():
        anotar("error", "NOTIFY_CHAT_IDS esta vacio: revisa el secreto en GitHub (Settings > Secrets > Actions).")
        raise SystemExit(1)

    fecha = ahora.date().isoformat()
    reservado = False
    if not forzar:
        if not database.reservar_aviso(TIPO_AVISO, fecha):
            anotar("notice", f"'{TIPO_AVISO}' de {fecha} ya se hizo en otra ejecucion: no se repite.")
            return
        reservado = True

    try:
        await scheduler.send_daily_handball_analysis()
    except Exception as e:
        if reservado:
            database.liberar_aviso(TIPO_AVISO, fecha)
        anotar("error", f"'{TIPO_AVISO}': error inesperado: {e}")
        raise SystemExit(1)

    if bot_handler.envios_fallidos:
        if reservado:
            database.liberar_aviso(TIPO_AVISO, fecha)
        anotar("error", f"Telegram RECHAZO {bot_handler.envios_fallidos} envio(s) (token o chat id incorrectos?): ver el registro.")
        raise SystemExit(1)
    anotar("notice", f"'{TIPO_AVISO}' de {fecha} completado.")


if __name__ == "__main__":
    asyncio.run(main())
