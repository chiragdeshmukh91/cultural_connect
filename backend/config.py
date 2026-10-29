"""Central configuration. All secrets come from the environment (.env), never from code."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


QLOO_API_KEY = os.getenv("QLOO_API_KEY", "").strip()
QLOO_BASE_URL = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com").rstrip("/")
QLOO_TIMEOUT = float(os.getenv("QLOO_TIMEOUT", "25"))
QLOO_MAX_RETRIES = int(os.getenv("QLOO_MAX_RETRIES", "2"))
QLOO_CACHE_TTL = int(os.getenv("QLOO_CACHE_TTL", "21600"))  # 6h

# Entity categories Qloo Insights supports as output (filter.type). Used for resolution + discovery.
ENTITY_TYPES = [
    "urn:entity:artist", "urn:entity:book", "urn:entity:brand", "urn:entity:destination",
    "urn:entity:movie", "urn:entity:person", "urn:entity:place", "urn:entity:podcast",
    "urn:entity:tv_show", "urn:entity:videogame",
]
# Output categories used to find shared cultural anchors for a group (comma-separated in env).
DISCOVERY_TYPES = [t.strip() for t in os.getenv(
    "DISCOVERY_TYPES", "urn:entity:book,urn:entity:podcast,urn:entity:movie,urn:entity:artist"
).split(",") if t.strip()]

# Audience parent types (Qloo /v2/audiences) — lets people connect over causes, politics, hobbies, life stage...
AUDIENCE_PARENT_TYPES = [
    "urn:audience:hobbies_and_interests", "urn:audience:global_issues", "urn:audience:communities",
    "urn:audience:political_preferences", "urn:audience:lifestyle_preferences_beliefs",
    "urn:audience:life_stage", "urn:audience:leisure", "urn:audience:professional_area",
    "urn:audience:investing_interests", "urn:audience:spending_habits",
]

# Optional LLM for the agentic planner. Without it a transparent rule-based planner is used.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none").strip().lower()  # none | openai | anthropic | gemini
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()  # OpenAI-compatible endpoints (Groq, Ollama, Azure...)

DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "data" / "culture_connect.db")))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if o.strip()]
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "12"))
