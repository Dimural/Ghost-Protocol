"""
Ghost Protocol — Adversarial AI Simulation Lab for Financial Fraud Detection
FastAPI Application Entry Point
"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.config import FRONTEND_URL
from backend.routes.criminal import router as criminal_router
from backend.routes.defender import router as defender_router
from backend.routes.match import router as match_router
from backend.routes.report import router as report_router
from backend.routes.websocket import router as websocket_router

app = FastAPI(
    title="Ghost Protocol",
    description="Adversarial AI Simulation Lab for Financial Fraud Detection",
    version="0.1.0",
)

# CORS middleware — allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(match_router)
app.include_router(criminal_router)
app.include_router(defender_router)
app.include_router(report_router)
app.include_router(websocket_router)


@app.get("/")
async def root():
    return {
        "project": "Ghost Protocol",
        "status": "operational",
        "description": "Adversarial AI Simulation Lab for Financial Fraud Detection",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
