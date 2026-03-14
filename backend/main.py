"""
Ghost Protocol — Adversarial AI Simulation Lab for Financial Fraud Detection
FastAPI Application Entry Point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Ghost Protocol",
    description="Adversarial AI Simulation Lab for Financial Fraud Detection",
    version="0.1.0",
)

# CORS middleware — allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Will be loaded from config later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
