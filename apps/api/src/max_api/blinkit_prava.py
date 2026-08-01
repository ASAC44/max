from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Callable
from urllib.parse import urlsplit


class ValidationError(ValueError):
    pass


class WorkflowStateError(RuntimeError):
    pass


class PravaError(RuntimeError):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(f"Prava request failed: {code}")
        self.status = status
        self.code = code


def _money(value: object, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,9}(?:\.\d{1,2})?", value):
        raise ValidationError("money values must be plain decimal strings")
    try:
        amount = Decimal(value).quantize(Decimal("0.01"))
    except InvalidOperation as error:
        raise ValidationError("money value is invalid") from error
    if amount < 0 or (positive and amount == 0):
        raise ValidationError("money value is out of range")
    return amount


def _text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValidationError(f"{name} must contain 1-{maximum} characters")
    return value.strip()


@dataclass(frozen=True)
class LineItem:
    product_id: str | None
    name: str
    variant: str
    unit_price: Decimal
    quantity: int

    @classmethod
    def parse(cls, value: object) -> LineItem:
        if not isinstance(value, dict) or set(value) != {
            "product_id",
            "name",
            "variant",
            "unit_price",
            "quantity",
        }:
            raise ValidationError("cart items have an invalid shape")
        product_id = value["product_id"]
        if product_id is not None:
            product_id = _text(product_id, "product_id", 100)
        quantity = value["quantity"]
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 99:
            raise ValidationError("quantity must be an integer from 1 to 99")
        return cls(
            product_id=product_id,
            name=_text(value["name"], "item name", 160),
            variant=_text(value["variant"], "item variant", 120),
            unit_price=_money(value["unit_price"], positive=True),
            quantity=quantity,
        )

    def public(self) -> dict[str, object]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "variant": self.variant,
            "unit_price": f"{self.unit_price:.2f}",
            "quantity": self.quantity,
        }


@dataclass(frozen=True)
class Adjustment:
    name: str
    amount: Decimal

    @classmethod
    def parse(cls, value: object) -> Adjustment:
        if not isinstance(value, dict) or set(value) != {"name", "amount"}:
            raise ValidationError("fee/discount entries have an invalid shape")
        return cls(
            name=_text(value["name"], "adjustment name", 120),
            amount=_money(value["amount"]),
        )

    def public(self) -> dict[str, str]:
        return {"name": self.name, "amount": f"{self.amount:.2f}"}


@dataclass(frozen=True)
class CartSnapshot:
    merchant: str
    merchant_url: str
    address_label: str
    currency: str
    items: tuple[LineItem, ...]
    fees: tuple[Adjustment, ...]
    discounts: tuple[Adjustment, ...]
    total: Decimal
    observed_at: str

    @classmethod
    def parse(cls, value: object) -> CartSnapshot:
        expected = {
            "merchant",
            "merchant_url",
            "address_label",
            "currency",
            "items",
            "fees",
            "discounts",
            "total",
            "observed_at",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValidationError("cart snapshot has an invalid shape")
        if value["merchant"] != "Blinkit" or value["merchant_url"] != "https://blinkit.com/":
            raise ValidationError("only Blinkit carts are supported")
        if value["currency"] != "INR":
            raise ValidationError("only INR carts are supported")
        if not isinstance(value["items"], list) or not 1 <= len(value["items"]) <= 50:
            raise ValidationError("cart must contain 1-50 items")
        if not isinstance(value["fees"], list) or len(value["fees"]) > 20:
            raise ValidationError("cart fees are invalid")
        if not isinstance(value["discounts"], list) or len(value["discounts"]) > 20:
            raise ValidationError("cart discounts are invalid")
        observed_at = _text(value["observed_at"], "observed_at", 64)
        try:
            datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValidationError("observed_at must be ISO 8601") from error

        snapshot = cls(
            merchant="Blinkit",
            merchant_url="https://blinkit.com/",
            address_label=_text(value["address_label"], "address_label", 80),
            currency="INR",
            items=tuple(LineItem.parse(item) for item in value["items"]),
            fees=tuple(Adjustment.parse(item) for item in value["fees"]),
            discounts=tuple(Adjustment.parse(item) for item in value["discounts"]),
            total=_money(value["total"], positive=True),
            observed_at=observed_at,
        )
        calculated = (
            sum((item.unit_price * item.quantity for item in snapshot.items), Decimal("0"))
            + sum((fee.amount for fee in snapshot.fees), Decimal("0"))
            - sum((discount.amount for discount in snapshot.discounts), Decimal("0"))
        )
        if calculated != snapshot.total:
            raise ValidationError(
                f"cart arithmetic mismatch: calculated {calculated:.2f}, total {snapshot.total:.2f}"
            )
        return snapshot

    def public(self) -> dict[str, object]:
        return {
            "merchant": self.merchant,
            "merchant_url": self.merchant_url,
            "address_label": self.address_label,
            "currency": self.currency,
            "items": [item.public() for item in self.items],
            "fees": [item.public() for item in self.fees],
            "discounts": [item.public() for item in self.discounts],
            "total": f"{self.total:.2f}",
            "observed_at": self.observed_at,
        }

    def fingerprint(self) -> str:
        comparable = self.public()
        comparable.pop("observed_at")
        return hashlib.sha256(
            json.dumps(comparable, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def compare_carts(expected: CartSnapshot, actual: CartSnapshot) -> list[dict[str, object]]:
    left = expected.public()
    right = actual.public()
    left.pop("observed_at")
    right.pop("observed_at")
    left["items"] = sorted(left["items"], key=lambda item: json.dumps(item, sort_keys=True))
    right["items"] = sorted(right["items"], key=lambda item: json.dumps(item, sort_keys=True))
    left["fees"] = sorted(left["fees"], key=lambda item: item["name"])
    right["fees"] = sorted(right["fees"], key=lambda item: item["name"])
    left["discounts"] = sorted(left["discounts"], key=lambda item: item["name"])
    right["discounts"] = sorted(right["discounts"], key=lambda item: item["name"])
    return [
        {"field": field, "expected": left[field], "actual": right[field]}
        for field in left
        if left[field] != right[field]
    ]


class PravaClient:
    def __init__(
        self,
        secret_key: str,
        base_url: str = "https://sandbox.api.prava.space",
        timeout: float = 15,
    ) -> None:
        if not secret_key.startswith("sk_test_"):
            raise ValueError("PRAVA_SECRET_KEY must be a sandbox key")
        if base_url != "https://sandbox.api.prava.space":
            raise ValueError("only the Prava sandbox API is supported")
        self.secret_key = secret_key
        self.base_url = base_url
        self.timeout = timeout

    def create_session(
        self,
        cart: CartSnapshot,
        *,
        user_id: str,
        user_email: str,
        external_order_ref: str,
    ) -> dict[str, object]:
        item_count = sum(item.quantity for item in cart.items)
        payload = {
            "user_id": user_id,
            "user_email": user_email,
            "total_amount": f"{cart.total:.2f}",
            "currency": cart.currency,
            "purchase_context": [
                {
                    "merchant_details": {
                        "name": cart.merchant,
                        "url": cart.merchant_url,
                        "country_code_iso2": "IN",
                    },
                    "product_details": [
                        {
                            "description": f"Blinkit order — {item_count} item(s), fees included",
                            "unit_price": f"{cart.total:.2f}",
                            "quantity": 1,
                        }
                    ],
                }
            ],
            "integration_type": "full_checkout",
            "callback_url": cart.merchant_url,
            "external_order_ref": external_order_ref,
        }
        return self._request("POST", "/v1/sessions", payload)

    def payment_result(self, session_id: str) -> dict[str, object]:
        return self._request("GET", f"/v1/sessions/{session_id}/payment-result")

    def report_status(
        self, session_id: str, txn_ref_id: str, status: str
    ) -> dict[str, object]:
        return self._request(
            "POST",
            f"/v1/sessions/{session_id}/report-status",
            {"txn_ref_id": txn_ref_id, "txn_status": status, "txn_type": "PURCHASE"},
        )

    def revoke(self, session_id: str) -> dict[str, object]:
        return self._request("POST", f"/v1/sessions/{session_id}/revoke")

    def _request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
            with response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise PravaError(response.status, "RESPONSE_TOO_LARGE")
                value = json.loads(raw)
        except urllib.error.HTTPError as error:
            try:
                value = json.loads(error.read(1_048_576))
                code = str(value.get("error", {}).get("code", "HTTP_ERROR"))
            except Exception:
                code = "HTTP_ERROR"
            raise PravaError(error.code, code) from None
        except (urllib.error.URLError, TimeoutError):
            raise PravaError(0, "NETWORK_ERROR") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise PravaError(0, "INVALID_RESPONSE") from None
        if not isinstance(value, dict):
            raise PravaError(0, "INVALID_RESPONSE")
        return value


@dataclass(repr=False)
class _Credential:
    token: str
    expiry_month: str
    expiry_year: str
    dynamic_cvv: str

    def __repr__(self) -> str:
        return "<PravaCredential redacted>"


@dataclass
class _Workflow:
    workflow_id: str
    user_id: str
    user_email: str
    share_url: str
    source_cart: CartSnapshot
    state: str = "cart_reviewed"
    imported_cart: CartSnapshot | None = None
    differences: list[dict[str, object]] = field(default_factory=list)
    session_id: str | None = None
    order_id: str | None = None
    iframe_url: str | None = None
    expires_at: str | None = None
    approval_token: str | None = None
    txn_ref_id: str | None = None
    credential: _Credential | None = field(default=None, repr=False)
    merchant_result: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class BlinkitPravaService:
    """Fail-closed Blinkit/Prava sandbox workflow for Max's agent and robot."""

    def __init__(
        self,
        prava: PravaClient,
        *,
        public_base_url: str,
        sandbox_enabled: bool = False,
        credential_injection_enabled: bool = False,
    ) -> None:
        public_url = urlsplit(public_base_url)
        if (
            public_url.scheme != "http"
            or public_url.hostname not in {"127.0.0.1", "localhost"}
            or public_url.username
            or public_url.password
            or public_url.path.rstrip("/")
            or public_url.query
            or public_url.fragment
        ):
            raise ValueError("commerce API must use a localhost public URL")
        self.prava = prava
        self.public_base_url = public_base_url.rstrip("/")
        self.sandbox_enabled = sandbox_enabled
        self.credential_injection_enabled = credential_injection_enabled
        self._workflows: dict[str, _Workflow] = {}
        # ponytail: process-local storage is enough for 15-minute sandbox sessions;
        # use encrypted durable state only if restart recovery becomes a requirement.
        self._lock = threading.RLock()

    def create_workflow(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict) or set(payload) != {
            "user_id",
            "user_email",
            "share_url",
            "cart",
        }:
            raise ValidationError("workflow requires user_id, user_email, share_url, and cart")
        user_id = _text(payload["user_id"], "user_id", 255)
        user_email = _text(payload["user_email"], "user_email", 254)
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", user_email):
            raise ValidationError("user_email is invalid")
        share_url = _text(payload["share_url"], "share_url", 2048)
        if not re.fullmatch(r"https://link\.blinkit\.com/bln/[A-Za-z0-9_-]+", share_url):
            raise ValidationError("share_url must be a Blinkit Share Cart URL")
        workflow = _Workflow(
            workflow_id=f"bpw_{uuid.uuid4().hex}",
            user_id=user_id,
            user_email=user_email,
            share_url=share_url,
            source_cart=CartSnapshot.parse(payload["cart"]),
        )
        with self._lock:
            self._workflows[workflow.workflow_id] = workflow
        return self._public(workflow)

    def verify_import(self, workflow_id: str, cart: object) -> dict[str, object]:
        with self._lock:
            workflow = self._get(workflow_id)
            if workflow.state not in {"cart_reviewed", "quote_mismatch"}:
                raise WorkflowStateError(f"cannot verify cart from {workflow.state}")
            workflow.imported_cart = CartSnapshot.parse(cart)
            workflow.differences = compare_carts(workflow.source_cart, workflow.imported_cart)
            workflow.state = "quote_mismatch" if workflow.differences else "browser_quote_verified"
            self._touch(workflow)
            return self._public(workflow)

    def create_prava_session(self, workflow_id: str) -> dict[str, object]:
        if not self.sandbox_enabled:
            raise WorkflowStateError("Prava sandbox is disabled")
        with self._lock:
            workflow = self._get(workflow_id)
            if workflow.state == "prava_session_created":
                return self._with_approval(workflow)
            if workflow.state != "browser_quote_verified":
                raise WorkflowStateError(f"cannot create Prava session from {workflow.state}")
            result = self.prava.create_session(
                workflow.source_cart,
                user_id=workflow.user_id,
                user_email=workflow.user_email,
                external_order_ref=workflow.workflow_id,
            )
            workflow.session_id = _text(result.get("session_id"), "session_id", 255)
            workflow.order_id = _text(result.get("order_id"), "order_id", 255)
            workflow.iframe_url = _text(result.get("iframe_url"), "iframe_url", 2048)
            if not workflow.iframe_url.startswith("https://sandbox.collect.prava.space/"):
                raise PravaError(0, "INVALID_IFRAME_URL")
            workflow.expires_at = _text(result.get("expires_at"), "expires_at", 64)
            workflow.approval_token = secrets.token_urlsafe(24)
            workflow.state = "prava_session_created"
            self._touch(workflow)
            return self._with_approval(workflow)

    def approval_redirect(self, workflow_id: str, token: str) -> str:
        with self._lock:
            workflow = self._get(workflow_id)
            if workflow.state not in {"prava_session_created", "approval_pending"}:
                raise WorkflowStateError(f"approval is unavailable from {workflow.state}")
            if not workflow.approval_token or not secrets.compare_digest(token, workflow.approval_token):
                raise ValidationError("invalid approval token")
            if not workflow.iframe_url:
                raise WorkflowStateError("approval URL is unavailable")
            workflow.state = "approval_pending"
            self._touch(workflow)
            return workflow.iframe_url

    def poll(self, workflow_id: str) -> dict[str, object]:
        with self._lock:
            workflow = self._get(workflow_id)
            if workflow.state not in {
                "prava_session_created",
                "approval_pending",
                "prava_pending",
                "awaiting_result",
            }:
                raise WorkflowStateError(f"cannot poll Prava from {workflow.state}")
            result = self.prava.payment_result(workflow.session_id or "")
            status = result.get("status")
            if status == "pending":
                workflow.state = "prava_pending"
            elif status == "failed":
                workflow.state = "prava_failed"
            elif status == "completed":
                workflow.state = "prava_completed"
            elif status == "awaiting_result":
                credential, txn_ref_id = self._extract_credential(result)
                workflow.credential = credential
                workflow.txn_ref_id = txn_ref_id
                workflow.state = "awaiting_result"
            else:
                raise PravaError(0, "INVALID_PAYMENT_STATE")
            self._touch(workflow)
            return self._public(workflow)

    def consume_credential(
        self,
        workflow_id: str,
        injector: Callable[[str, str, str, str], object],
    ) -> object:
        if not self.credential_injection_enabled:
            raise WorkflowStateError("Prava credential injection is disabled")
        with self._lock:
            workflow = self._get(workflow_id)
            if workflow.state != "awaiting_result" or workflow.credential is None:
                raise WorkflowStateError("credential is unavailable or already consumed")
            credential = workflow.credential
            workflow.credential = None
            workflow.state = "credential_consumed"
            self._touch(workflow)
        return injector(
            credential.token,
            credential.expiry_month,
            credential.expiry_year,
            credential.dynamic_cvv,
        )

    def record_merchant_result(self, workflow_id: str, result: str) -> dict[str, object]:
        if result not in {"APPROVED", "DECLINED", "UNKNOWN"}:
            raise ValidationError("merchant result must be APPROVED, DECLINED, or UNKNOWN")
        with self._lock:
            workflow = self._get(workflow_id)
            if workflow.state != "credential_consumed":
                raise WorkflowStateError(f"cannot record merchant result from {workflow.state}")
            if result == "UNKNOWN":
                workflow.state = "merchant_unknown"
            else:
                self.prava.report_status(
                    workflow.session_id or "", workflow.txn_ref_id or "", result
                )
                workflow.state = "reconciled"
            workflow.merchant_result = result
            self._touch(workflow)
            return self._public(workflow)

    def revoke(self, workflow_id: str) -> dict[str, object]:
        with self._lock:
            workflow = self._get(workflow_id)
            if workflow.session_id and workflow.state not in {
                "reconciled",
                "revoked",
                "prava_failed",
                "prava_completed",
            }:
                self.prava.revoke(workflow.session_id)
            workflow.credential = None
            workflow.state = "revoked"
            self._touch(workflow)
            return self._public(workflow)

    def get(self, workflow_id: str) -> dict[str, object]:
        with self._lock:
            return self._public(self._get(workflow_id))

    @staticmethod
    def _extract_credential(result: dict[str, object]) -> tuple[_Credential, str]:
        transactions = result.get("transactions")
        if not isinstance(transactions, list):
            raise PravaError(0, "CREDENTIAL_MISSING")
        for transaction in transactions:
            if not isinstance(transaction, dict):
                continue
            line_items = transaction.get("line_items")
            if not isinstance(line_items, list):
                continue
            for line in line_items:
                if not isinstance(line, dict) or line.get("status") != "awaiting_result":
                    continue
                values = [
                    line.get("token"),
                    line.get("expiry_month"),
                    line.get("expiry_year"),
                    line.get("dynamic_cvv"),
                    line.get("txn_ref_id"),
                ]
                if all(isinstance(value, str) and value for value in values):
                    return _Credential(*values[:4]), values[4]
        raise PravaError(0, "CREDENTIAL_MISSING")

    def _with_approval(self, workflow: _Workflow) -> dict[str, object]:
        result = self._public(workflow)
        result["approval_url"] = (
            f"{self.public_base_url}/api/blinkit-prava/workflows/"
            f"{workflow.workflow_id}/approve?token={workflow.approval_token}"
        )
        return result

    def _get(self, workflow_id: str) -> _Workflow:
        if not re.fullmatch(r"bpw_[0-9a-f]{32}", workflow_id):
            raise KeyError(workflow_id)
        try:
            return self._workflows[workflow_id]
        except KeyError:
            raise KeyError(workflow_id) from None

    @staticmethod
    def _touch(workflow: _Workflow) -> None:
        workflow.updated_at = datetime.now(UTC).isoformat()

    @staticmethod
    def _redact(value: str | None) -> str | None:
        if not value:
            return None
        return value if len(value) <= 12 else f"{value[:8]}***{value[-4:]}"

    def _public(self, workflow: _Workflow) -> dict[str, object]:
        return {
            "workflow_id": workflow.workflow_id,
            "state": workflow.state,
            "share_url": workflow.share_url,
            "cart_fingerprint": workflow.source_cart.fingerprint(),
            "cart_total": f"{workflow.source_cart.total:.2f}",
            "currency": workflow.source_cart.currency,
            "address_label": workflow.source_cart.address_label,
            "item_count": sum(item.quantity for item in workflow.source_cart.items),
            "differences": workflow.differences,
            "prava_session_id": self._redact(workflow.session_id),
            "prava_order_id": self._redact(workflow.order_id),
            "prava_expires_at": workflow.expires_at,
            "credential_ready": workflow.credential is not None,
            "merchant_result": workflow.merchant_result,
            "created_at": workflow.created_at,
            "updated_at": workflow.updated_at,
        }
