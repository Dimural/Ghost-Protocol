"""
Ghost Protocol — Configuration
Loads environment variables from .env file.
If GROQ_API_KEY is missing/empty, all Groq-backed agents fall back to mock responses automatically.
"""
from dotenv import load_dotenv
import os
from pathlib import Path

# Load .env from the project root (one level above backend/)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# --- LLM ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip() or None
# Support both legacy GEMINI_API_KEY and the newer GOOGLE_API_KEY naming.
GEMINI_API_KEY = (
    os.getenv("GOOGLE_API_KEY", "").strip()
    or os.getenv("GEMINI_API_KEY", "").strip()
    or None
)
GEMINI_API_BASE_URL = os.getenv(
    "GEMINI_API_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta",
).rstrip("/")
GEMINI_FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash").strip()
GEMINI_PRO_MODEL = os.getenv("GEMINI_PRO_MODEL", "gemini-2.5-pro").strip()
WATSONX_API_KEY = os.getenv("WATSONX_API_KEY", "").strip() or None
WATSONX_PROJECT_ID = os.getenv("WATSONX_PROJECT_ID", "").strip() or None

# --- Redis ---
REDIS_URL = os.getenv("REDIS_URL", "").strip() or None

# --- App ---
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")

# --- Derived flags ---
USE_MOCK_LLM = not bool(GROQ_API_KEY)
"""
When True, all AI agents (Criminal, Police, Generator, Report) will return
hardcoded mock data instead of calling Groq-backed runtime paths.
Set GROQ_API_KEY in .env to activate real Groq calls — zero code changes needed.
"""
