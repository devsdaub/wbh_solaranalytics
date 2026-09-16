import struct

import httpx
import pytest

from app.adapters.hoymiles_api import parse_protobuf_chart
from app.adapters.open_meteo_weather import to_open_meteo_azimuth
from app.retry import mit_wiederholung


@pytest.mark.parametrize("nord_basiert, erwartet", [
    (203, 23),    # die eigene Anlage, Südwest
    (180, 0),     # Süd
    (90, -90),    # Ost
])
def test_azimut_wird_sued_basiert(nord_basiert, erwartet):
    """Anlagendaten sind nord-basiert, Open-Meteo rechnet süd-basiert.
    Ein falscher Azimut fällt nicht auf, die API antwortet trotzdem."""
    assert to_open_meteo_azimuth(nord_basiert) == erwartet


def varint(zahl: int) -> bytes:
    ausgabe = bytearray()
    while True:
        byte = zahl & 0x7F
        zahl >>= 7
        ausgabe.append(byte | 0x80 if zahl else byte)
        if not zahl:
            return bytes(ausgabe)


def laengenfeld(feld: int, inhalt: bytes) -> bytes:
    return varint(feld << 3 | 2) + varint(len(inhalt)) + inhalt


def test_protobuf_parser_liest_beschriftungen_und_werte():
    """Nachgebaut, was die Hoymiles-API liefert: Feld 1 die Tagesnummern,
    Feld 2 eine Reihe mit Namen und Werten als 32-Bit-Fliesskomma."""
    labels = b"".join(laengenfeld(1, str(tag).encode()) for tag in (1, 2, 3))
    reihe = laengenfeld(1, b"pv_eq") + laengenfeld(
        2, struct.pack("<3f", 1000.0, 2500.0, 0.0)
    )

    geparst = parse_protobuf_chart(labels + laengenfeld(2, reihe))

    assert geparst["labels"] == ["1", "2", "3"]
    assert geparst["pv_eq"] == [1000.0, 2500.0, 0.0]


@pytest.fixture
def ohne_warten(monkeypatch):
    """Sonst wartet der Test drei Sekunden auf den Backoff."""
    monkeypatch.setattr("app.retry.time.sleep", lambda sekunden: None)


def antwort(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("GET", "https://example.test"))


def test_serverfehler_wird_dreimal_versucht(ohne_warten):
    versuche = []

    def aufruf():
        versuche.append(1)
        return antwort(503)

    with pytest.raises(httpx.HTTPStatusError):
        mit_wiederholung(aufruf)

    assert len(versuche) == 3


def test_falsche_anfrage_wird_nicht_wiederholt(ohne_warten):
    """Ein 400 wird durch Warten nicht besser. Aufgefallen an einem
    Tippfehler in sources.yaml, der drei identische Anfragen erzeugte."""
    versuche = []

    def aufruf():
        versuche.append(1)
        return antwort(400)

    with pytest.raises(httpx.HTTPStatusError):
        mit_wiederholung(aufruf)

    assert len(versuche) == 1
