"""
Loads configuration from environment variables (or a local .env file).
"""
import os
from pathlib import Path

# Load .env file manually so we don't force a dependency on python-dotenv.
# Prefer the repo-local file, but also support running from a different cwd.
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        # Treat empty environment values as unset so .env can supply them.
        if not os.environ.get(key):
            os.environ[key] = value


_load_dotenv(Path.cwd() / ".env")
_load_dotenv(Path(__file__).resolve().parent / ".env")

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/api")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:70b")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")
GROQ_MODEL_FALLBACKS = [
    model.strip()
    for model in os.getenv(
        "GROQ_MODEL_FALLBACKS",
        "llama-3.1-70b-versatile,llama-3.1-8b-instant",
    ).split(",")
    if model.strip()
]

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "")

REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "60"))
