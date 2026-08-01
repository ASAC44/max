import os
from pathlib import Path
from urllib.parse import urlparse

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


def swiggy_cdp_url() -> str:
    value = os.getenv("SWIGGY_CDP_URL", "http://127.0.0.1:9222")
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("SWIGGY_CDP_URL must be a loopback HTTP URL")
    return value


def swiggy_cardholder_name() -> str:
    value = os.getenv("SWIGGY_CARDHOLDER_NAME", "").strip()
    if not value:
        raise RuntimeError("SWIGGY_CARDHOLDER_NAME is required for automated Swiggy checkout")
    return value


def checkout_timeout_seconds() -> float:
    try:
        value = float(os.getenv("SWIGGY_CHECKOUT_TIMEOUT_SECONDS", "20"))
    except ValueError as exc:
        raise RuntimeError("SWIGGY_CHECKOUT_TIMEOUT_SECONDS must be a number") from exc
    if not 5 <= value <= 60:
        raise RuntimeError("SWIGGY_CHECKOUT_TIMEOUT_SECONDS must be between 5 and 60")
    return value
