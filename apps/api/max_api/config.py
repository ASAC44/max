import os
from ipaddress import ip_address
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


def robot_base_url() -> str:
    value = os.getenv("MAX_ROBOT_BASE_URL", "").rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    host = parsed.hostname or ""
    try:
        local = ip_address(host).is_private or ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost"
    if parsed.scheme != "http" or not local:
        raise RuntimeError("MAX_ROBOT_BASE_URL must be loopback or private-LAN HTTP")
    return value


def robot_operator_pin() -> str:
    value = os.getenv("MAX_ROBOT_OPERATOR_PIN", "")
    if len(value) < 4:
        raise RuntimeError("MAX_ROBOT_OPERATOR_PIN must contain at least four characters")
    return value


def robot_outbound_seconds() -> float:
    try:
        value = float(os.getenv("MAX_ROBOT_OUTBOUND_SECONDS", "30"))
    except ValueError as exc:
        raise RuntimeError("MAX_ROBOT_OUTBOUND_SECONDS must be a number") from exc
    if not 1 <= value <= 3600:
        raise RuntimeError("MAX_ROBOT_OUTBOUND_SECONDS must be between 1 and 3600")
    return value


def dispatch_buffer_seconds() -> float:
    try:
        value = float(os.getenv("MAX_DISPATCH_BUFFER_SECONDS", "60"))
    except ValueError as exc:
        raise RuntimeError("MAX_DISPATCH_BUFFER_SECONDS must be a number") from exc
    if not 0 <= value <= 900:
        raise RuntimeError("MAX_DISPATCH_BUFFER_SECONDS must be between 0 and 900")
    return value
