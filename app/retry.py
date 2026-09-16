import logging
import time

import httpx

logger = logging.getLogger(__name__)

VERSUCHE = 3
BASIS_SEKUNDEN = 1.0

# 4xx ist ein Fehler in der eigenen Anfrage und wird durch Warten nicht besser.
# Ausnahmen sind Zeitüberschreitung und Drosselung, die beschreiben einen Zustand.
WIEDERHOLBAR = {408, 425, 429, 500, 502, 503, 504}


def ist_wiederholbar(fehler: Exception) -> bool:
    """Trennt vorübergehende Störungen von dauerhaften Fehlern."""
    if isinstance(fehler, httpx.HTTPStatusError):
        return fehler.response.status_code in WIEDERHOLBAR
    return isinstance(fehler, httpx.RequestError)


def mit_wiederholung(aufruf, versuche: int = VERSUCHE) -> httpx.Response:
    """Führt einen HTTP-Aufruf aus und wiederholt ihn bei Störungen."""
    for versuch in range(1, versuche + 1):
        try:
            antwort = aufruf()
            antwort.raise_for_status()
            return antwort
        except httpx.HTTPError as fehler:
            if versuch == versuche or not ist_wiederholbar(fehler):
                raise
            wartezeit = BASIS_SEKUNDEN * 2 ** (versuch - 1)
            logger.warning(
                "Versuch %s von %s fehlgeschlagen (%s), erneut in %.0f s",
                versuch, versuche, _kurzform(fehler), wartezeit,
            )
            time.sleep(wartezeit)


def _kurzform(fehler: Exception) -> str:
    if isinstance(fehler, httpx.HTTPStatusError):
        return f"HTTP {fehler.response.status_code}"
    return type(fehler).__name__
