import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text

from app.api.data import router as data_router
from app.api.routes import router as api_router
from app.api.settings import router as settings_router
from app.api.upload import router as upload_router
from app.config import load_plant_config, load_scheduler_config, load_sources_config
from app.database import Base, SessionLocal, engine
from app.filters import als_lokalzeit, zeitzone_kuerzel
from app.models import DailyFact, PipelineRun, PlantConfig
from app.pipeline.auswertung import baue_heatmap
from app.pipeline.ingestion import _current_plant_id
from app.pipeline.scheduler import scheduler_status, start_scheduler, stop_scheduler
from app.pipeline.transformation import find_weather_gaps
from app.stammdaten import seed_plant_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    seed_plant_config()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="SolarPipeline",
    description="Datenpipeline für ein Balkonkraftwerk in Stuttgart",
    version="0.1.0",
    lifespan=lifespan,
)

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["lokal"] = als_lokalzeit

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(api_router)
app.include_router(upload_router)
app.include_router(data_router)
app.include_router(settings_router)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_status = "ok"
    except Exception as error:
        database_status = f"nicht erreichbar: {type(error).__name__}"

    return {"status": "ok", "database": database_status}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    settings = load_plant_config()

    with SessionLocal() as session:
        plant = session.execute(
            select(PlantConfig).where(PlantConfig.name == settings.name)
        ).scalar_one()
        plant_id = plant.id

        tage = session.execute(
            select(DailyFact)
            .where(DailyFact.plant_id == plant_id)
            .order_by(DailyFact.date.desc())
            .limit(21)
        ).scalars().all()

        tage_gesamt, tage_mit_produktion, summe_kwh, eq_mittel = session.execute(
            select(
                func.count(DailyFact.id),
                func.count(DailyFact.production_kwh),
                func.sum(DailyFact.production_kwh),
                func.avg(DailyFact.eq),
            ).where(DailyFact.plant_id == plant_id)
        ).one()

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "tage": tage,
            "tage_gesamt": tage_gesamt,
            "tage_mit_produktion": tage_mit_produktion,
            "summe_kwh": summe_kwh,
            "eq_mittel": eq_mittel,
            "heatmap": baue_heatmap(plant_id),
            "zeitzone": zeitzone_kuerzel(),
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    gespeichert: str | None = None,
    tage: int | None = None,
    zeilen: int | None = None,
):
    status = scheduler_status()

    with SessionLocal() as session:
        plant_id = _current_plant_id(session)

        laeufe = session.execute(
            select(PipelineRun).order_by(PipelineRun.id.desc()).limit(25)
        ).scalars().all()

        letzter_lauf = laeufe[0] if laeufe else None

    naechster = None
    if status["naechster_lauf"]:
        naechster = datetime.fromisoformat(status["naechster_lauf"])

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "status": status,
            "scheduler": load_scheduler_config(),
            "quellen": load_sources_config(),
            "wetterluecken": find_weather_gaps(plant_id),
            "laeufe": laeufe,
            "letzter_lauf": letzter_lauf,
            "naechster": naechster,
            "gespeichert": gespeichert,
            "tage": tage,
            "zeilen": zeilen,
            "zeitzone": zeitzone_kuerzel(),
        },
    )