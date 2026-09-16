import hashlib
import logging
import time
from base64 import b64encode

import httpx

from app.retry import mit_wiederholung

logger = logging.getLogger(__name__)

TOKEN_TTL = 23 * 3600


class HoymilesAuthError(Exception):
    pass


def api_ok(status) -> bool:
    """Die API liefert den Status mal als Zeichenkette, mal als Zahl."""
    try:
        return int(status) == 0
    except (TypeError, ValueError):
        return False


def _hash_legacy(passwort: str) -> str:
    md5_hex = hashlib.md5(passwort.encode()).hexdigest()
    sha256_b64 = b64encode(hashlib.sha256(passwort.encode()).digest()).decode()
    return f"{md5_hex}.{sha256_b64}"


def _hash_argon2(passwort: str, salt_hex: str) -> str:
    try:
        from argon2.low_level import Type, hash_secret_raw
    except ImportError as fehler:
        raise HoymilesAuthError(
            "argon2-cffi fehlt in den Abhängigkeiten"
        ) from fehler

    roh = hash_secret_raw(
        secret=passwort.encode("utf-8"),
        salt=bytes.fromhex(salt_hex),
        time_cost=3,
        memory_cost=32768,
        parallelism=1,
        hash_len=32,
        type=Type.ID,
    )
    return roh.hex()


class HoymilesAuth:
    """Hält das Anmeldetoken und erneuert es bei Bedarf."""

    def __init__(self, username: str, password: str, base_url: str):
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._token: str | None = None
        self._token_zeit: float = 0.0

    def token(self) -> str:
        if not self._token or (time.time() - self._token_zeit) >= TOKEN_TTL:
            self._anmelden()
        return self._token

    def verwerfen(self) -> None:
        self._token = None
        self._token_zeit = 0.0

    def header(self) -> dict:
        # authorization kleingeschrieben, ohne Bearer-Präfix
        return {"authorization": self.token(), "Content-Type": "application/json"}

    def _anmelden(self) -> None:
        with httpx.Client(timeout=30) as client:
            antwort = mit_wiederholung(
                lambda: client.post(
                    f"{self._base_url}/iam/pub/3/auth/pre-insp",
                    json={"u": self._username},
                )
            )
            vorab = antwort.json()

            daten = vorab.get("data") or {}
            nonce = daten.get("n", "")
            salt = daten.get("a")
            version = daten.get("v", 2)

            if not api_ok(vorab.get("status")) or not nonce:
                raise HoymilesAuthError(f"Voranfrage fehlgeschlagen: {vorab}")

            if salt and version == 3:
                hash_wert = _hash_argon2(self._password, salt)
            else:
                hash_wert = _hash_legacy(self._password)

            antwort = mit_wiederholung(
                lambda: client.post(
                    f"{self._base_url}/iam/pub/3/auth/login",
                    json={"u": self._username, "ch": hash_wert, "n": nonce},
                )
            )
            login = antwort.json()

            if not api_ok(login.get("status")):
                raise HoymilesAuthError(
                    f"Anmeldung fehlgeschlagen (v={version}): {login.get('message')}"
                )

            token = (login.get("data") or {}).get("token")
            if not token:
                raise HoymilesAuthError(f"Kein Token in der Antwort: {login}")

            self._token = token
            self._token_zeit = time.time()
            logger.info("Hoymiles-Anmeldung erfolgreich, Kontoversion %s", version)
