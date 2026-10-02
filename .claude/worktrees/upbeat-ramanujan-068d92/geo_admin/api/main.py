"""
GEO Admin API

Internal admin backend for managing GEO Collector pipeline.
Provides REST API for viewing requests/tasks/results and triggering jobs.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import database
from routers import requests, tasks, stats, clients, reports, analysis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("GeoAdmin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection lifecycle."""
    logger.info("Connecting to database...")
    await database.connect()
    logger.info("Database connected.")
    yield
    logger.info("Disconnecting from database...")
    await database.disconnect()
    logger.info("Database disconnected.")


app = FastAPI(
    title="GEO Admin API",
    description="Internal admin API for GEO Collector",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(stats.router, prefix="/api", tags=["Stats"])
app.include_router(requests.router, prefix="/api", tags=["Requests"])
app.include_router(tasks.router, prefix="/api", tags=["Tasks"])
app.include_router(clients.router, prefix="/api", tags=["Clients"])
app.include_router(reports.router, prefix="/api", tags=["Reports"])
app.include_router(analysis.router, prefix="/api", tags=["Analysis"])


@app.get("/health")
def health_check():
    return {"status": "ok"}
