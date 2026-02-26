from fastapi import FastAPI

import models  # noqa: F401 — triggers Base.metadata.create_all
from database import Base, get_db
from routes import games, events, players, stats

app = FastAPI(title="AirPLAi Event Tagging API")

app.include_router(games.router)
app.include_router(events.router)
app.include_router(players.router)
app.include_router(stats.router)
