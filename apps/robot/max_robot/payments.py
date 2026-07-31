from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


class PaymentValidationError(ValueError):
    pass


class PaymentGatewayError(RuntimeError):
    pass


class PaymentService:
    """Create test-mode Stripe checkouts without handling payment credentials."""

    def __init__(
        self,
        *,
        secret_key: str,
        webhook_secret: str,
        api_key: str,
        public_base_url: str,
        database: str | Path,
        stripe_module: Any | None = None,
    ) -> None:
        if not secret_key.startswith("sk_test_"):
            raise ValueError("STRIPE_SECRET_KEY must be a test-mode secret key")
        if not webhook_secret.startswith("whsec_"):
            raise ValueError("STRIPE_WEBHOOK_SECRET must start with whsec_")
        if len(api_key) < 16:
            raise ValueError("MAX_PAYMENT_API_KEY must contain at least 16 characters")
        if not public_base_url.startswith(("http://", "https://")):
            raise ValueError("MAX_PUBLIC_BASE_URL must be an HTTP(S) URL")

        if stripe_module is None:
            try:
                import stripe as stripe_module
            except ImportError as exc:
                raise RuntimeError("install stripe==15.3.1 to enable payments") from exc
        stripe_module.api_key = secret_key
        self.stripe = stripe_module
        self.webhook_secret = webhook_secret
        self.api_key = api_key
        self.public_base_url = public_base_url.rstrip("/")
        self.database = str(Path(database).expanduser())
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize_database()

    @classmethod
    def from_environment(cls) -> PaymentService:
        required = {
            name: os.environ.get(name, "")
            for name in (
                "STRIPE_SECRET_KEY",
                "STRIPE_WEBHOOK_SECRET",
                "MAX_PAYMENT_API_KEY",
            )
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"missing payment configuration: {', '.join(missing)}")
        return cls(
            secret_key=required["STRIPE_SECRET_KEY"],
            webhook_secret=required["STRIPE_WEBHOOK_SECRET"],
            api_key=required["MAX_PAYMENT_API_KEY"],
            public_base_url=os.environ.get(
                "MAX_PUBLIC_BASE_URL", "http://127.0.0.1:8080"
            ),
            database=os.environ.get(
                "MAX_PAYMENT_DB", "~/.local/state/max/payments.sqlite3"
            ),
        )

    def create_checkout(self, payload: object) -> tuple[dict[str, object], bool]:
        order_id, currency, items, total = self._validate_order(payload)
        with self._lock:
            existing = self._find_by_order(order_id)
            if existing:
                return existing, True

            payment_id = f"pay_{uuid.uuid4().hex}"
            metadata = {"payment_id": payment_id, "order_id": order_id}
            try:
                session = self.stripe.checkout.Session.create(
                    mode="payment",
                    payment_method_types=["card"],
                    client_reference_id=order_id,
                    success_url=(
                        f"{self.public_base_url}/payments/success"
                        f"?payment_id={payment_id}"
                    ),
                    cancel_url=(
                        f"{self.public_base_url}/payments/cancel"
                        f"?payment_id={payment_id}"
                    ),
                    line_items=[
                        {
                            "price_data": {
                                "currency": "inr",
                                "product_data": {"name": item["name"]},
                                "unit_amount": int(item["unit_price"] * 100),
                            },
                            "quantity": item["quantity"],
                        }
                        for item in items
                    ],
                    metadata=metadata,
                    payment_intent_data={"metadata": metadata},
                    idempotency_key=(
                        "max-checkout-"
                        + hashlib.sha256(order_id.encode()).hexdigest()
                    ),
                )
                stripe_session_id = str(self._field(session, "id"))
                checkout_url = str(self._field(session, "url"))
                if not stripe_session_id.startswith(
                    "cs_test_"
                ) or not checkout_url.startswith("https://checkout.stripe.com/"):
                    raise ValueError("Stripe returned an invalid test checkout")
            except Exception as exc:
                raise PaymentGatewayError("Stripe checkout creation failed") from exc

            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO payments (
                        payment_id, order_id, currency, total_amount, status,
                        stripe_session_id, checkout_url
                    ) VALUES (?, ?, ?, ?, 'checkout_created', ?, ?)
                    """,
                    (
                        payment_id,
                        order_id,
                        currency,
                        f"{total:.2f}",
                        stripe_session_id,
                        checkout_url,
                    ),
                )
            return self.get_payment(payment_id), False

    def get_payment(self, payment_id: str) -> dict[str, object] | None:
        if not payment_id.startswith("pay_") or len(payment_id) > 40:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payment_id, order_id, currency, total_amount, status,
                       stripe_session_id, checkout_url, failure_code,
                       failure_message, created_at, updated_at
                FROM payments WHERE payment_id = ?
                """,
                (payment_id,),
            ).fetchone()
        return dict(row) if row else None

    def handle_webhook(self, payload: bytes, signature: str) -> dict[str, object]:
        try:
            event = self.stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
        except Exception as exc:
            raise PaymentValidationError("invalid Stripe webhook") from exc

        event_id = str(self._field(event, "id"))
        event_type = str(self._field(event, "type"))
        if not event_id.startswith("evt_"):
            raise PaymentValidationError("invalid Stripe event ID")

        statuses = {
            "payment_intent.payment_failed": "payment_failed",
            "payment_intent.succeeded": "paid",
            "checkout.session.completed": "paid",
            "checkout.session.expired": "expired",
        }
        new_status = statuses.get(event_type)
        if not new_status:
            return {"received": True, "ignored": True}

        data = self._field(event, "data")
        stripe_object = self._field(data, "object")
        metadata = self._field(stripe_object, "metadata") or {}
        payment_id = str(self._field(metadata, "payment_id") or "")
        error = self._field(stripe_object, "last_payment_error") or {}
        failure_code = self._field(error, "decline_code") or self._field(error, "code")

        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO stripe_events (event_id, event_type) VALUES (?, ?)",
                    (event_id, event_type),
                )
            except sqlite3.IntegrityError:
                return {"received": True, "duplicate": True}

            row = connection.execute(
                "SELECT status FROM payments WHERE payment_id = ?", (payment_id,)
            ).fetchone()
            if not row:
                return {"received": True, "matched": False}
            current = row["status"]
            if current == "paid" or (current == "expired" and new_status != "paid"):
                return {"received": True, "matched": True, "status": current}
            connection.execute(
                """
                UPDATE payments
                SET status = ?, failure_code = ?, failure_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE payment_id = ?
                """,
                (
                    new_status,
                    str(failure_code)[:100] if failure_code else None,
                    "Payment failed" if new_status == "payment_failed" else None,
                    payment_id,
                ),
            )
        return {"received": True, "matched": True, "status": new_status}

    def _find_by_order(self, order_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payment_id FROM payments WHERE order_id = ?", (order_id,)
            ).fetchone()
        return self.get_payment(row["payment_id"]) if row else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    payment_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL UNIQUE,
                    currency TEXT NOT NULL,
                    total_amount TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stripe_session_id TEXT NOT NULL UNIQUE,
                    checkout_url TEXT NOT NULL,
                    failure_code TEXT,
                    failure_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS stripe_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    @staticmethod
    def _field(value: object, name: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(name)
        return getattr(value, name, None)

    @staticmethod
    def _validate_order(
        payload: object,
    ) -> tuple[str, str, list[dict[str, Any]], Decimal]:
        if not isinstance(payload, dict) or set(payload) != {
            "order_id",
            "currency",
            "items",
        }:
            raise PaymentValidationError(
                "expected exactly order_id, currency, and items"
            )
        order_id = payload["order_id"]
        if not isinstance(order_id, str) or not 1 <= len(order_id.strip()) <= 200:
            raise PaymentValidationError("order_id must contain 1-200 characters")
        currency = payload["currency"]
        if not isinstance(currency, str) or currency.upper() != "INR":
            raise PaymentValidationError("only INR is supported")
        raw_items = payload["items"]
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 20:
            raise PaymentValidationError("items must contain 1-20 entries")

        items: list[dict[str, Any]] = []
        total = Decimal("0")
        for raw in raw_items:
            if not isinstance(raw, dict) or set(raw) != {
                "name",
                "unit_price",
                "quantity",
            }:
                raise PaymentValidationError(
                    "each item requires exactly name, unit_price, and quantity"
                )
            name = raw["name"]
            quantity = raw["quantity"]
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
                raise PaymentValidationError("item name must contain 1-120 characters")
            if (
                isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or not 1 <= quantity <= 99
            ):
                raise PaymentValidationError("quantity must be an integer from 1 to 99")
            if not isinstance(raw["unit_price"], str):
                raise PaymentValidationError("unit_price must be a decimal string")
            if not re.fullmatch(r"\d{1,9}(?:\.\d{1,2})?", raw["unit_price"]):
                raise PaymentValidationError(
                    "unit_price must be a plain decimal with at most two decimals"
                )
            try:
                unit_price = Decimal(raw["unit_price"])
            except InvalidOperation as exc:
                raise PaymentValidationError("unit_price is invalid") from exc
            if (
                not unit_price.is_finite()
                or unit_price <= 0
                or unit_price.as_tuple().exponent < -2
            ):
                raise PaymentValidationError(
                    "unit_price must be positive with at most two decimals"
                )
            unit_price = unit_price.quantize(Decimal("0.01"))
            items.append(
                {"name": name.strip(), "unit_price": unit_price, "quantity": quantity}
            )
            total += unit_price * quantity
        return order_id.strip(), "INR", items, total
