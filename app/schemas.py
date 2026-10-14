import logging

import pandera.pandas as pa
from pandera.errors import SchemaErrors

logger = logging.getLogger(__name__)

WETTER_SPALTEN = {
    "gti": pa.Column(float, pa.Check.ge(0), nullable=True),
    "temperature": pa.Column(float, pa.Check.in_range(-40, 55), nullable=True),
    "cloud_cover": pa.Column("Int64", pa.Check.in_range(0, 100), nullable=True),
    "cloud_cover_low": pa.Column("Int64", pa.Check.in_range(0, 100), nullable=True),
    "cloud_cover_mid": pa.Column("Int64", pa.Check.in_range(0, 100), nullable=True),
    "cloud_cover_high": pa.Column("Int64", pa.Check.in_range(0, 100), nullable=True),
    "visibility": pa.Column(float, pa.Check.ge(0), nullable=True),
    "sunshine_duration": pa.Column(float, pa.Check.in_range(0, 3600), nullable=True),
}

HOURLY_WEATHER_SCHEMA = pa.DataFrameSchema(
    {
        "plant_id": pa.Column(int),
        "timestamp": pa.Column("datetime64[ns, UTC]", unique=True),
        **WETTER_SPALTEN,
    },
    strict=True,
    coerce=True,
)

HOURLY_AIR_SCHEMA = pa.DataFrameSchema(
    {
        "plant_id": pa.Column(int),
        "timestamp": pa.Column("datetime64[ns, UTC]", unique=True),
        "dust": pa.Column(float, pa.Check.ge(0), nullable=True),
        "pm10": pa.Column(float, pa.Check.ge(0), nullable=True),
        "aerosol_od": pa.Column(float, pa.Check.ge(0), nullable=True),
    },
    strict=True,
    coerce=True,
)

HOURLY_SATELLIT_SCHEMA = pa.DataFrameSchema(
    {
        "plant_id": pa.Column(int),
        "timestamp": pa.Column("datetime64[ns, UTC]", unique=True),
        "gti_satellit": pa.Column(float, pa.Check.in_range(0, 1500), nullable=True),
    },
    strict=True,
    coerce=True,
)

HOURLY_FORECAST_SCHEMA = pa.DataFrameSchema(
    {
        "plant_id": pa.Column(int),
        "timestamp": pa.Column("datetime64[ns, UTC]"),
        "vorlauf": pa.Column(int, pa.Check.in_range(1, 16)),
        "gti": WETTER_SPALTEN["gti"],
        "temperature": WETTER_SPALTEN["temperature"],
        "cloud_cover": WETTER_SPALTEN["cloud_cover"],
        "sunshine_duration": WETTER_SPALTEN["sunshine_duration"],
    },
    unique=["timestamp", "vorlauf"],
    strict=True,
    coerce=True,
)

VORHERSAGE_SCHEMA = pa.DataFrameSchema(
    {
        "plant_id": pa.Column(int),
        "timestamp": pa.Column("datetime64[ns, UTC]", unique=True),
        **WETTER_SPALTEN,
        "precipitation": pa.Column(float, pa.Check.ge(0), nullable=True),
    },
    strict=True,
    coerce=True,
)

ENERGY_REPORT_SCHEMA = pa.DataFrameSchema(
    {
        "plant_id": pa.Column(int),
        "date": pa.Column("datetime64[ns]", unique=True),
        "production_kwh": pa.Column(float, pa.Check.in_range(0, 20)),
    },
    strict=True,
    coerce=True,
)


def validiere_nachsichtig(schema, frame, quelle: str):
    """Validiert. Unplausible Einzelwerte werden NULL, die Zeile bleibt."""
    try:
        return schema.validate(frame, lazy=True)
    except SchemaErrors as fehler:
        bereinigt = _werte_verwerfen(schema, frame, fehler, quelle)

    return schema.validate(bereinigt, lazy=True)


def _werte_verwerfen(schema, frame, fehler: SchemaErrors, quelle: str):
    faelle = fehler.failure_cases

    nullbar = {name for name, spalte in schema.columns.items() if spalte.nullable}
    heilbar = faelle[faelle["index"].notna() & faelle["column"].isin(nullbar)]

    if len(heilbar) < len(faelle):
        raise fehler

    bereinigt = frame.copy()
    for spalte, gruppe in heilbar.groupby("column"):
        zeilen = gruppe["index"].tolist()
        bereinigt.loc[zeilen, spalte] = None
        logger.warning(
            "%s: %s Wert(e) in %s verworfen, Beispiel %s",
            quelle, len(zeilen), spalte, gruppe["failure_case"].iloc[0],
        )

    return bereinigt
