"""FastAPI application entry point.

Serves the API and, when a built frontend bundle exists, the static app from
the same process so the whole thing deploys as one container on one port.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import ROOT_DIR
from app.routes.jobs import router as jobs_router
from app.worker import start_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    stop_event = start_worker()
    yield
    stop_event.set()


app = FastAPI(title="Classroom Voice Analytics", lifespan=lifespan)

# Dev only: the Vite dev server runs on another port. In production the
# bundle is served below from the same origin and this list is harmless.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)

frontend_dist = ROOT_DIR / "frontend" / "dist"
if frontend_dist.exists():
    app.mount(
        "/", StaticFiles(directory=frontend_dist, html=True), name="frontend"
    )
