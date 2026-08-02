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


def prava_environment() -> str:
    secret = os.getenv("PRAVA_SECRET_KEY", "").strip()
    inferred = (
        "sandbox"
        if secret.startswith("sk_test_")
        else "production"
        if secret.startswith("sk_live_")
        else ""
    )
    value = os.getenv("PRAVA_ENVIRONMENT", inferred).strip().lower()
    if value not in {"sandbox", "production"}:
        raise RuntimeError(
            "PRAVA_ENVIRONMENT must be 'sandbox' or 'production' and the secret key must be configured"
        )
    expected_prefix = "sk_test_" if value == "sandbox" else "sk_live_"
    if not secret.startswith(expected_prefix):
        raise RuntimeError(
            f"PRAVA_SECRET_KEY must use the {expected_prefix} prefix for {value}"
        )
    return value


def purchase_enabled() -> bool:
    """Global kill switch for external merchant checkout submission."""
    return os.getenv("MAX_PURCHASE_ENABLED", "false").lower() == "true"


def runtime_environment() -> str:
    value = os.getenv("MAX_RUNTIME_ENVIRONMENT", "local")
    if value not in {"local", "production"}:
        raise RuntimeError("MAX_RUNTIME_ENVIRONMENT must be 'local' or 'production'")
    return value


def robot_mode() -> str:
    mode = os.getenv("MAX_ROBOT_MODE", "simulated")
    if mode not in {"simulated", "pi", "pi_poll"}:
        raise RuntimeError("MAX_ROBOT_MODE must be 'simulated', 'pi', or 'pi_poll'")
    return mode


def robot_url() -> str:
    value = os.getenv("MAX_ROBOT_URL", "http://127.0.0.1:8081").rstrip("/")
    parsed = urlparse(value)
    try:
        host = ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise RuntimeError("MAX_ROBOT_URL must use a literal private or loopback IP address") from exc
    if parsed.scheme != "http" or not (host.is_private or host.is_loopback):
        raise RuntimeError("MAX_ROBOT_URL must be a private or loopback HTTP URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("MAX_ROBOT_URL must not contain credentials, query, or fragment")
    return value


def robot_token() -> str:
    value = os.getenv("MAX_ROBOT_TOKEN", "")
    if len(value) < 24:
        raise RuntimeError("MAX_ROBOT_TOKEN must contain at least 24 characters")
    return value


def robot_dry_run() -> bool:
    return os.getenv("MAX_ROBOT_DRY_RUN", "true").lower() != "false"


def robot_heartbeat_stale_seconds() -> float:
    try:
        value = float(os.getenv("MAX_ROBOT_HEARTBEAT_STALE_SECONDS", "30"))
    except ValueError as exc:
        raise RuntimeError("MAX_ROBOT_HEARTBEAT_STALE_SECONDS must be a number") from exc
    if not 5 <= value <= 300:
        raise RuntimeError("MAX_ROBOT_HEARTBEAT_STALE_SECONDS must be between 5 and 300")
    return value


def teleop_enabled() -> bool:
    return os.getenv("MAX_TELEOP_ENABLED", "false").lower() == "true"


def teleop_deadman_ms() -> int:
    try:
        value = int(os.getenv("MAX_TELEOP_DEADMAN_MS", "350"))
    except ValueError as exc:
        raise RuntimeError("MAX_TELEOP_DEADMAN_MS must be an integer") from exc
    if not 150 <= value <= 1_000:
        raise RuntimeError("MAX_TELEOP_DEADMAN_MS must be between 150 and 1000")
    return value


def teleop_max_client_age_ms() -> int:
    try:
        value = int(os.getenv("MAX_TELEOP_MAX_CLIENT_AGE_MS", "1000"))
    except ValueError as exc:
        raise RuntimeError("MAX_TELEOP_MAX_CLIENT_AGE_MS must be an integer") from exc
    if not 250 <= value <= 5_000:
        raise RuntimeError("MAX_TELEOP_MAX_CLIENT_AGE_MS must be between 250 and 5000")
    return value


def teleop_controller_idle_seconds() -> float:
    try:
        value = float(os.getenv("MAX_TELEOP_CONTROLLER_IDLE_SECONDS", "6"))
    except ValueError as exc:
        raise RuntimeError("MAX_TELEOP_CONTROLLER_IDLE_SECONDS must be a number") from exc
    if not 3 <= value <= 60:
        raise RuntimeError("MAX_TELEOP_CONTROLLER_IDLE_SECONDS must be between 3 and 60")
    return value


def teleop_agent_idle_seconds() -> float:
    try:
        value = float(os.getenv("MAX_TELEOP_AGENT_IDLE_SECONDS", "10"))
    except ValueError as exc:
        raise RuntimeError("MAX_TELEOP_AGENT_IDLE_SECONDS must be a number") from exc
    if not 5 <= value <= 60:
        raise RuntimeError("MAX_TELEOP_AGENT_IDLE_SECONDS must be between 5 and 60")
    return value


def teleop_state_file() -> Path:
    return Path(os.getenv("MAX_TELEOP_STATE_FILE", "/tmp/max-teleop-state.json"))


def web_origin() -> str:
    value = os.getenv("MAX_WEB_ORIGIN", "http://127.0.0.1:5173").rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("MAX_WEB_ORIGIN must be an HTTP(S) origin without a path")
    return value


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


def order_sync_interval_seconds() -> float:
    try:
        value = float(os.getenv("MAX_ORDER_SYNC_INTERVAL_SECONDS", "5"))
    except ValueError as exc:
        raise RuntimeError("MAX_ORDER_SYNC_INTERVAL_SECONDS must be a number") from exc
    if not 2 <= value <= 60:
        raise RuntimeError("MAX_ORDER_SYNC_INTERVAL_SECONDS must be between 2 and 60")
    return value


def order_sync_error_interval_seconds() -> float:
    try:
        value = float(os.getenv("MAX_ORDER_SYNC_ERROR_INTERVAL_SECONDS", "30"))
    except ValueError as exc:
        raise RuntimeError("MAX_ORDER_SYNC_ERROR_INTERVAL_SECONDS must be a number") from exc
    if not 5 <= value <= 300:
        raise RuntimeError("MAX_ORDER_SYNC_ERROR_INTERVAL_SECONDS must be between 5 and 300")
    return value


def order_sync_state_file() -> Path:
    return Path(
        os.getenv(
            "MAX_ORDER_SYNC_STATE_FILE",
            "/tmp/max-order-sync-worker.json",
        )
    )


def telegram_bot_token() -> str:
    value = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if len(value) < 20 or ":" not in value:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    return value


def telegram_webhook_secret() -> str:
    value = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not 24 <= len(value) <= 128 or not value.replace("_", "").replace("-", "").isalnum():
        raise RuntimeError(
            "TELEGRAM_WEBHOOK_SECRET must contain 24-128 letters, numbers, underscores, or hyphens"
        )
    return value


def telegram_owner_user_id() -> int:
    try:
        value = int(os.getenv("TELEGRAM_OWNER_USER_ID", ""))
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_OWNER_USER_ID must be an integer") from exc
    if value <= 0:
        raise RuntimeError("TELEGRAM_OWNER_USER_ID must be a positive integer")
    return value


def telegram_control_api_url() -> str:
    value = os.getenv("MAX_CONTROL_API_URL", "http://127.0.0.1:8000").rstrip("/")
    parsed = urlparse(value)
    is_loopback_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not is_loopback_http:
        raise RuntimeError("MAX_CONTROL_API_URL must use HTTPS or loopback HTTP")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("MAX_CONTROL_API_URL must not contain credentials, query, or fragment")
    return value


def telegram_auto_checkout() -> bool:
    return os.getenv("MAX_TELEGRAM_AUTO_CHECKOUT", "false").lower() == "true"


def telegram_worker_interval_seconds() -> float:
    try:
        value = float(os.getenv("MAX_TELEGRAM_WORKER_INTERVAL_SECONDS", "5"))
    except ValueError as exc:
        raise RuntimeError("MAX_TELEGRAM_WORKER_INTERVAL_SECONDS must be a number") from exc
    if not 1 <= value <= 60:
        raise RuntimeError("MAX_TELEGRAM_WORKER_INTERVAL_SECONDS must be between 1 and 60")


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
