import os
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]


def database_url() -> str:
    return os.getenv("MAX_DATABASE_URL", f"sqlite:///{API_ROOT / 'max.db'}")


def agent_mode() -> str:
    mode = os.getenv("MAX_AGENT_MODE", "simulated")
    if mode not in {"simulated", "openai"}:
        raise RuntimeError("MAX_AGENT_MODE must be 'simulated' or 'openai'")
    return mode


def commerce_mode() -> str:
    mode = os.getenv("MAX_COMMERCE_MODE", "simulated")
    if mode not in {"simulated", "swiggy"}:
        raise RuntimeError("MAX_COMMERCE_MODE must be 'simulated' or 'swiggy'")
    return mode


def payment_mode() -> str:
    mode = os.getenv("MAX_PAYMENT_MODE", "simulated")
    if mode not in {"simulated", "prava"}:
        raise RuntimeError("MAX_PAYMENT_MODE must be 'simulated' or 'prava'")
    return mode


def web_origin() -> str:
    return os.getenv("MAX_WEB_ORIGIN", "http://127.0.0.1:5173")


def admin_token() -> str:
    value = os.getenv("MAX_ADMIN_TOKEN", "")
    if len(value) < 24 or value == "replace-with-a-long-random-value":
        return ""
    return value


def openai_timeout_seconds() -> float:
    try:
        value = float(os.getenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "30"))
    except ValueError as exc:
        raise RuntimeError("OPENAI_REQUEST_TIMEOUT_SECONDS must be a number") from exc
    if not 0.01 <= value <= 120:
        raise RuntimeError("OPENAI_REQUEST_TIMEOUT_SECONDS must be between 0.01 and 120")
    return value
