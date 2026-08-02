import asyncio
import json
import os
import re
import subprocess
from dataclasses import dataclass, field as dataclass_field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent
from playwright.async_api import async_playwright

from .config import (
    checkout_timeout_seconds,
    prava_environment,
    robot_token,
    robot_url,
    swiggy_cardholder_name,
    swiggy_cdp_url,
)
from .models import utcnow
from .schemas import Environment, ProviderResult, Quote, QuoteLine, ShoppingIntent


class IntegrationError(RuntimeError):
    """A safe external-integration error whose message contains no provider data."""


class SwiggyConnectionError(IntegrationError):
    """A transient MCP transport failure before merchant checkout."""


def _nested_integration_error(exc: BaseException) -> IntegrationError | None:
    """Recover a safe provider error wrapped by an AnyIO task group."""
    if isinstance(exc, IntegrationError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            if nested := _nested_integration_error(child):
                return nested
    return None


@dataclass(frozen=True)
class PravaSession:
    session_id: str
    order_id: str
    approval_url: str
    expires_at: str


@dataclass(frozen=True)
class PravaPaymentState:
    status: str
    txn_ref_id: str | None
    credential_fields_present: bool


@dataclass(frozen=True)
class PravaCredential:
    txn_ref_id: str
    token: str = dataclass_field(repr=False)
    dynamic_cvv: str = dataclass_field(repr=False)
    expiry_month: str = dataclass_field(repr=False)
    expiry_year: str = dataclass_field(repr=False)


@dataclass(frozen=True)
class RobotDispatchAck:
    mission_id: str
    command_id: str
    status: str
    dry_run: bool
    motion_started: bool


@dataclass(frozen=True)
class SwiggyOrderSnapshot:
    provider_order_id: str
    raw_status: str
    eta_text: str | None = None


class BrowserCheckoutError(IntegrationError):
    """A safe failure raised only before the merchant submit click."""


class RobotClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def dispatch(
        self,
        *,
        mission_id: str,
        command_id: str,
        destination: str,
        dry_run: bool,
    ) -> RobotDispatchAck:
        payload = {
            "schema_version": 1,
            "mission_id": mission_id,
            "command_id": command_id,
            "destination": destination,
            "dry_run": dry_run,
        }
        try:
            async with httpx.AsyncClient(
                base_url=robot_url(),
                transport=self.transport,
                timeout=5,
                trust_env=False,
            ) as client:
                response = await client.post(
                    "/api/v1/missions/dispatch",
                    headers={"Authorization": f"Bearer {robot_token()}"},
                    json=payload,
                )
        except (httpx.HTTPError, RuntimeError) as exc:
            raise IntegrationError("Pi robot bridge connection failed") from exc
        if response.status_code != 200:
            raise IntegrationError("Pi robot bridge rejected the mission")
        try:
            data = response.json()
            ack = RobotDispatchAck(
                mission_id=data["mission_id"],
                command_id=data["command_id"],
                status=data["status"],
                dry_run=data["dry_run"],
                motion_started=data["motion_started"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrationError("Pi robot bridge returned an invalid acknowledgement") from exc
        if (
            ack.mission_id != mission_id
            or ack.command_id != command_id
            or ack.status != "ACKNOWLEDGED"
            or ack.dry_run != dry_run
        ):
            raise IntegrationError("Pi robot bridge acknowledgement did not match the command")
        if dry_run and ack.motion_started:
            raise IntegrationError("Pi robot bridge reported motion during a dry run")
        return ack


def _minor(value: Any) -> int:
    cleaned = re.sub(r"[^0-9.-]", "", str(value))
    try:
        return int(Decimal(cleaned) * 100)
    except (InvalidOperation, ValueError) as exc:
        raise IntegrationError("Swiggy returned an unreadable price") from exc


def _find(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = _find(value, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find(value, key)
            if found is not None:
                return found
    return None


def _list(data: Any, key: str) -> list[dict[str, Any]]:
    value = _find(data, key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _dicts(data: Any):
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from _dicts(value)
    elif isinstance(data, list):
        for value in data:
            yield from _dicts(value)


def _text(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _tool_payload(result: Any) -> dict[str, Any]:
    if result.isError:
        raise IntegrationError("Swiggy rejected an MCP operation")
    if isinstance(result.structuredContent, dict):
        return result.structuredContent
    for block in result.content:
        if isinstance(block, TextContent):
            try:
                value = json.loads(block.text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    raise IntegrationError("Swiggy returned an unsupported MCP response")


def _tool_arguments(tool: Any, values: dict[str, Any]) -> dict[str, Any]:
    properties = tool.inputSchema.get("properties", {})
    arguments = {key: value for key, value in values.items() if key in properties and value is not None}
    if missing := set(tool.inputSchema.get("required", [])) - arguments.keys():
        raise IntegrationError(f"Swiggy tool contract changed; missing {', '.join(sorted(missing))}")
    return arguments


class SwiggyClient:
    endpoint = "https://mcp.swiggy.com/im"

    @classmethod
    def _server(cls) -> StdioServerParameters:
        # The container installs a version-pinned bridge. Invoking it directly
        # avoids an npm registry lookup and an unreviewed package update in the
        # middle of an owner request.
        return StdioServerParameters(command="mcp-remote", args=[cls.endpoint])

    async def readiness(self) -> dict[str, Any]:
        required = {
            "get_addresses",
            "search_products",
            "update_cart",
            "get_cart",
            "clear_cart",
            "get_orders",
            "track_order",
        }
        server = self._server()
        try:
            async with asyncio.timeout(30):
                async with stdio_client(server, errlog=subprocess.DEVNULL) as (
                    read,
                    write,
                ):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        available = {
                            tool.name for tool in (await session.list_tools()).tools
                        }
        except Exception as exc:
            if nested := _nested_integration_error(exc):
                raise nested from exc
            raise IntegrationError(
                "Swiggy MCP readiness failed; complete OAuth in the deployed OS user"
            ) from exc
        missing = sorted(required - available)
        if missing:
            raise IntegrationError("Swiggy MCP is missing required Instamart tools")
        return {
            "connected": True,
            "required_tools_present": True,
            "tool_count": len(available),
        }

    async def order_snapshot(
        self,
        *,
        provider_order_id: str | None,
        quote: Quote,
    ) -> SwiggyOrderSnapshot:
        """Read and minimally normalize one order without retaining raw PII."""
        server = self._server()
        try:
            async with stdio_client(server, errlog=subprocess.DEVNULL) as (
                read,
                write,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = {
                        tool.name: tool for tool in (await session.list_tools()).tools
                    }
                    if "get_orders" not in tools:
                        raise IntegrationError(
                            "Swiggy MCP is missing the required get_orders status tool"
                        )
                    if provider_order_id and "track_order" in tools:
                        payload = _tool_payload(
                            await session.call_tool(
                                "track_order",
                                _tool_arguments(
                                    tools["track_order"],
                                    {
                                        "orderId": provider_order_id,
                                        "order_id": provider_order_id,
                                        "id": provider_order_id,
                                    },
                                ),
                            )
                        )
                    else:
                        payload = _tool_payload(
                            await session.call_tool(
                                "get_orders",
                                _tool_arguments(tools["get_orders"], {}),
                            )
                        )
        except IntegrationError:
            raise
        except Exception as exc:
            if nested := _nested_integration_error(exc):
                raise nested from exc
            raise IntegrationError(
                "Swiggy order status connection failed; complete OAuth setup and retry"
            ) from exc
        return self._select_order_snapshot(payload, provider_order_id, quote)

    @staticmethod
    def _order_id(value: dict[str, Any]) -> str | None:
        for node in _dicts(value):
            candidate = _text(
                node,
                "orderId",
                "order_id",
                "orderID",
                "orderNumber",
                "order_number",
            )
            if candidate:
                return candidate
        return None

    @staticmethod
    def _order_status(value: dict[str, Any]) -> str | None:
        specific = (
            "orderStatus",
            "order_status",
            "deliveryStatus",
            "delivery_status",
            "statusText",
            "status_text",
        )
        for node in _dicts(value):
            if candidate := _text(node, *specific):
                return candidate
        return _text(value, "status")

    @staticmethod
    def _order_amount(value: dict[str, Any]) -> int | None:
        for key in (
            "orderTotal",
            "order_total",
            "totalAmount",
            "total_amount",
            "cartTotalAmount",
        ):
            candidate = _find(value, key)
            if candidate is not None:
                try:
                    return _minor(candidate)
                except IntegrationError:
                    return None
        return None

    @staticmethod
    def _order_item_names(value: dict[str, Any]) -> list[str]:
        names: list[str] = []
        for node in _dicts(value):
            candidate = _text(
                node,
                "displayName",
                "productName",
                "itemName",
                "name",
                "title",
            )
            if candidate and candidate not in names:
                names.append(candidate)
        return names[:50]

    @classmethod
    def _select_order_snapshot(
        cls,
        payload: dict[str, Any],
        provider_order_id: str | None,
        quote: Quote,
    ) -> SwiggyOrderSnapshot:
        candidates = _list(payload, "orders")
        if not candidates:
            candidates = [
                node
                for node in _dicts(payload)
                if cls._order_id(node) and cls._order_status(node)
            ]
        if (
            provider_order_id
            and not candidates
            and cls._order_status(payload)
        ):
            candidates = [payload]
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            order_id = cls._order_id(candidate) or provider_order_id
            if order_id and order_id not in seen:
                seen.add(order_id)
                unique.append(candidate)
        candidates = unique

        if provider_order_id:
            candidates = [
                candidate
                for candidate in candidates
                if cls._order_id(candidate) in {None, provider_order_id}
            ]
        else:
            matching: list[dict[str, Any]] = []
            wanted = quote.product_name.casefold()
            for candidate in candidates:
                amount = cls._order_amount(candidate)
                names = cls._order_item_names(candidate)
                if amount is None and not names:
                    continue
                if amount is not None and amount != quote.amount_minor:
                    continue
                if names and not any(
                    wanted in name.casefold() or name.casefold() in wanted
                    for name in names
                ):
                    continue
                matching.append(candidate)
            candidates = matching

        if len(candidates) != 1:
            raise IntegrationError(
                "Swiggy order status could not be correlated to exactly one approved order"
            )
        selected = candidates[0]
        order_id = provider_order_id or cls._order_id(selected)
        raw_status = cls._order_status(selected)
        if not order_id or not raw_status:
            raise IntegrationError("Swiggy returned an incomplete order status")
        eta = None
        for node in _dicts(selected):
            eta = _text(
                node,
                "eta",
                "etaText",
                "eta_text",
                "deliveryEta",
                "delivery_eta",
            )
            if eta:
                break
        return SwiggyOrderSnapshot(
            provider_order_id=order_id[:128],
            raw_status=raw_status[:80],
            eta_text=eta[:80] if eta else None,
        )

    async def quote(self, intent: ShoppingIntent) -> Quote:
        server = self._server()
        try:
            async with stdio_client(server, errlog=subprocess.DEVNULL) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                    required = {"get_addresses", "search_products", "update_cart", "get_cart", "clear_cart"}
                    if not required.issubset(tools):
                        raise IntegrationError("Swiggy MCP is missing a required Instamart tool")

                    addresses = _tool_payload(await session.call_tool("get_addresses", {}))
                    address = self._select_address(addresses, intent.destination or "")
                    address_id = _text(address, "addressId", "address_id", "id")
                    if not address_id:
                        raise IntegrationError("Swiggy returned an address without an ID")

                    existing = _tool_payload(await session.call_tool(
                        "get_cart",
                        _tool_arguments(tools["get_cart"], {"addressId": address_id, "address_id": address_id}),
                    ))
                    if self._cart_has_items(existing):
                        _tool_payload(await session.call_tool(
                            "clear_cart",
                            _tool_arguments(tools["clear_cart"], {"addressId": address_id, "address_id": address_id}),
                        ))
                        cleared = _tool_payload(await session.call_tool(
                            "get_cart",
                            _tool_arguments(tools["get_cart"], {"addressId": address_id, "address_id": address_id}),
                        ))
                        if self._cart_has_items(cleared):
                            raise IntegrationError("Swiggy cart could not be cleared before starting the mission")

                    search = _tool_payload(await session.call_tool(
                        "search_products",
                        _tool_arguments(tools["search_products"], {
                            "addressId": address_id,
                            "address_id": address_id,
                            "query": intent.item,
                        }),
                    ))
                    product_name, spin_id, unit_price = self._select_product(search)
                    quantity = intent.quantity or 1
                    _tool_payload(await session.call_tool(
                        "update_cart",
                        _tool_arguments(tools["update_cart"], {
                            "selectedAddressId": address_id,
                            "items": [{"spinId": spin_id, "quantity": quantity}],
                            "addressId": address_id,
                            "address_id": address_id,
                            "spinId": spin_id,
                            "spin_id": spin_id,
                            "quantity": quantity,
                        }),
                    ))
                    cart = _tool_payload(await session.call_tool(
                        "get_cart",
                        _tool_arguments(tools["get_cart"], {"addressId": address_id, "address_id": address_id}),
                    ))
                    self._assert_cart_serviceable(cart)
                    total = self._cart_total(cart)
        except IntegrationError:
            raise
        except Exception as exc:
            if nested := _nested_integration_error(exc):
                raise nested from exc
            raise SwiggyConnectionError(
                "Swiggy MCP connection failed; complete OAuth setup and retry"
            ) from exc

        if intent.budget_max_minor is not None and total > intent.budget_max_minor:
            raise IntegrationError("Swiggy quote exceeds the owner's maximum budget")
        product_total = unit_price * quantity
        lines = [QuoteLine(description=product_name, unit_price_minor=unit_price, quantity=quantity)]
        if total > product_total:
            lines.append(QuoteLine(description="Swiggy fees", unit_price_minor=total - product_total, quantity=1))
        return Quote(
            revision=1,
            merchant="SWIGGY_INSTAMART",
            product_name=product_name,
            variant_id=spin_id,
            quantity=quantity,
            amount_minor=total,
            currency="INR",
            destination=intent.destination or "",
            environment=Environment.PRODUCTION,
            expires_at=utcnow() + timedelta(minutes=15),
            line_items=lines,
        )

    async def verify_quote(self, quote: Quote) -> None:
        """Re-read the live cart immediately before the one-shot browser submit."""
        server = self._server()
        try:
            async with stdio_client(server, errlog=subprocess.DEVNULL) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                    if not {"get_addresses", "get_cart"}.issubset(tools):
                        raise IntegrationError("Swiggy MCP is missing a required cart verification tool")
                    address = self._select_address(
                        _tool_payload(await session.call_tool("get_addresses", {})), quote.destination
                    )
                    address_id = _text(address, "addressId", "address_id", "id")
                    if not address_id:
                        raise IntegrationError("Swiggy returned an address without an ID")
                    cart = _tool_payload(await session.call_tool(
                        "get_cart",
                        _tool_arguments(tools["get_cart"], {"addressId": address_id, "address_id": address_id}),
                    ))
        except IntegrationError:
            raise
        except Exception as exc:
            if nested := _nested_integration_error(exc):
                raise nested from exc
            raise IntegrationError("Swiggy cart verification failed; do not submit payment") from exc

        self._assert_cart_serviceable(cart)
        if self._cart_total(cart) != quote.amount_minor:
            raise IntegrationError("Swiggy cart total changed after approval; do not submit payment")
        matching = [node for node in _dicts(cart) if _text(node, "spinId", "spin_id") == quote.variant_id]
        if not matching:
            raise IntegrationError("Swiggy cart item changed after approval; do not submit payment")
        quantities = [_find(node, "quantity") for node in matching]
        quantities += [_find(node, "qty") for node in matching]
        try:
            matches_quantity = quote.quantity in {int(value) for value in quantities if value is not None}
        except (TypeError, ValueError):
            matches_quantity = False
        if not matches_quantity:
            raise IntegrationError("Swiggy cart quantity changed after approval; do not submit payment")

    @staticmethod
    def _select_address(payload: dict[str, Any], destination: str) -> dict[str, Any]:
        addresses = _list(payload, "addresses")
        if not addresses:
            raise IntegrationError("Swiggy account has no saved serviceable address")
        wanted = re.sub(r"\s+", " ", destination.strip().lower())
        wanted = re.sub(r"^(?:my\s+)?saved\s+", "", wanted)
        wanted = re.sub(r"\s+address$", "", wanted)
        wanted = "work" if wanted == "office" else wanted
        for address in addresses:
            label = _text(address, "addressCategory", "label", "type")
            if label and label.lower() == wanted:
                return address
        if len(addresses) == 1:
            return addresses[0]
        raise IntegrationError("No saved Swiggy address matches the requested destination")

    @staticmethod
    def _cart_has_items(payload: dict[str, Any]) -> bool:
        count = _find(payload, "totalItems")
        if count is not None:
            try:
                return int(count) > 0
            except (TypeError, ValueError):
                return True
        return bool(_list(payload, "items"))

    @staticmethod
    def _select_product(payload: dict[str, Any]) -> tuple[str, str, int]:
        for product in _list(payload, "products"):
            name = _text(product, "displayName", "productName", "name", "title")
            variations = product.get("variations") if isinstance(product.get("variations"), list) else [product]
            for variation in variations:
                if not isinstance(variation, dict) or variation.get("isInStockAndAvailable") is False:
                    continue
                spin_id = _text(variation, "spinId", "spin_id")
                price = _find(variation, "offerPrice")
                if spin_id and name and price is not None:
                    return name, spin_id, _minor(price)
        raise IntegrationError("Swiggy returned no purchasable result")

    @staticmethod
    def _cart_total(payload: dict[str, Any]) -> int:
        total = _find(payload, "cartTotalAmount")
        if total is None:
            total = _find(payload, "total")
        if total is None:
            raise IntegrationError("Swiggy cart response has no total")
        return _minor(total)

    @staticmethod
    def _assert_cart_serviceable(payload: dict[str, Any]) -> None:
        warning = _find(payload, "cartWarning")
        texts = [_text(payload, "message") or ""]
        if isinstance(warning, dict):
            texts.append(_text(warning, "message") or "")
        if any("not serviceable" in text.lower() for text in texts):
            raise IntegrationError("Selected Swiggy address is currently not serviceable; choose another address")


class PravaClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.secret = os.getenv("PRAVA_SECRET_KEY", "")
        self.user_id = os.getenv("PRAVA_USER_ID", "")
        self.user_email = os.getenv("PRAVA_USER_EMAIL", "")
        self.callback_url = os.getenv("PRAVA_CALLBACK_URL", "")
        self.transport = transport
        try:
            self.environment = prava_environment()
        except RuntimeError as exc:
            raise IntegrationError(str(exc)) from exc
        self.base_url = (
            "https://sandbox.api.prava.space"
            if self.environment == "sandbox"
            else "https://api.prava.space"
        )
        self.approval_host = (
            "sandbox.collect.prava.space"
            if self.environment == "sandbox"
            else "checkout.prava.space"
        )
        if not self.user_id or not self.user_email:
            raise IntegrationError("PRAVA_USER_ID and PRAVA_USER_EMAIL are required")
        if self.callback_url and urlparse(self.callback_url).scheme != "https":
            raise IntegrationError("PRAVA_CALLBACK_URL must be empty or HTTPS for hosted checkout")

    async def readiness(self) -> dict[str, Any]:
        """Check the configured service without creating a payment session."""
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=10,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.get("/health")
        except httpx.HTTPError as exc:
            raise IntegrationError("Prava health check failed") from exc
        if response.status_code != 200:
            raise IntegrationError("Prava health check was rejected")
        try:
            body = response.json()
        except ValueError as exc:
            raise IntegrationError("Prava health response was unreadable") from exc
        if not isinstance(body, dict) or body.get("status") != "ok":
            raise IntegrationError("Prava health response was unexpected")
        return {
            "configured": True,
            "connected": True,
            "environment": self.environment,
            "money_mode": (
                "test_only" if self.environment == "sandbox" else "live"
            ),
            "credential_validation": (
                "run explicit sandbox session smoke"
                if self.environment == "sandbox"
                else "production key accepted; run an explicitly authorized live checkout"
            ),
        }

    async def create_session(self, quote: Quote) -> PravaSession:
        lines = quote.line_items or [QuoteLine(
            description=quote.product_name,
            unit_price_minor=quote.amount_minor,
            quantity=1,
        )]
        payload = {
            "user_id": self.user_id,
            "user_email": self.user_email,
            "total_amount": f"{Decimal(quote.amount_minor) / 100:.2f}",
            "currency": quote.currency,
            "integration_type": "full_checkout",
            "purchase_context": [{
                "merchant_details": {
                    "name": "Swiggy Instamart",
                    "url": "https://www.swiggy.com/instamart",
                    "country_code_iso2": "IN",
                },
                "product_details": [{
                    "description": line.description,
                    "unit_price": f"{Decimal(line.unit_price_minor) / 100:.2f}",
                    "quantity": line.quantity,
                } for line in lines],
            }],
        }
        if self.callback_url:
            payload["callback_url"] = self.callback_url
        data = await self._request("POST", "/v1/sessions", json=payload)
        try:
            result = PravaSession(
                session_id=data["session_id"],
                order_id=data["order_id"],
                approval_url=data["iframe_url"],
                expires_at=data["expires_at"],
            )
        except (KeyError, TypeError) as exc:
            raise IntegrationError("Prava session response is incomplete") from exc
        parsed = urlparse(result.approval_url)
        if parsed.scheme != "https" or parsed.hostname != self.approval_host:
            raise IntegrationError("Prava returned an unexpected approval URL")
        return result

    async def payment_state(self, session_id: str) -> PravaPaymentState:
        data = await self._request("GET", f"/v1/sessions/{session_id}/payment-result")
        status = data.get("status")
        if status not in {"pending", "awaiting_result", "completed", "failed"}:
            raise IntegrationError("Prava returned an unknown payment state")
        line = next(iter(_list(data, "line_items")), {})
        return PravaPaymentState(
            status=status,
            txn_ref_id=_text(line, "txn_ref_id"),
            credential_fields_present=all(line.get(key) for key in (
                "token", "dynamic_cvv", "expiry_month", "expiry_year"
            )),
        )

    async def revoke_session(self, session_id: str) -> None:
        data = await self._request("POST", f"/v1/sessions/{session_id}/revoke")
        if data.get("success") is not True:
            raise IntegrationError("Prava did not confirm payment-session revocation")

    async def credential(self, session_id: str) -> PravaCredential:
        data = await self._request("GET", f"/v1/sessions/{session_id}/payment-result")
        if data.get("status") != "awaiting_result":
            raise IntegrationError("Prava credential is not ready for merchant checkout")
        line = next(iter(_list(data, "line_items")), {})
        values = {
            key: str(line.get(key, "")).strip()
            for key in ("txn_ref_id", "token", "dynamic_cvv", "expiry_month", "expiry_year")
        }
        if not (
            values["txn_ref_id"]
            and re.fullmatch(r"\d{12,19}", values["token"])
            and re.fullmatch(r"\d{3,4}", values["dynamic_cvv"])
            and re.fullmatch(r"(?:0?[1-9]|1[0-2])", values["expiry_month"])
            and re.fullmatch(r"\d{2}|\d{4}", values["expiry_year"])
        ):
            raise IntegrationError("Prava returned an incomplete or invalid scoped credential")
        return PravaCredential(**values)

    async def report_result(self, session_id: str, txn_ref_id: str, status: str) -> PravaPaymentState:
        if status not in {"APPROVED", "DECLINED"}:
            raise IntegrationError("Only a confirmed merchant result can be reported to Prava")
        expected_state = "completed" if status == "APPROVED" else "failed"
        state = await self.payment_state(session_id)
        if state.status in {"completed", "failed"}:
            if state.status != expected_state:
                raise IntegrationError("Prava final state contradicts the merchant result")
            return state
        if state.status != "awaiting_result" or state.txn_ref_id != txn_ref_id:
            raise IntegrationError("Prava session is not ready to accept the merchant result")
        confirmation = await self._request("POST", f"/v1/sessions/{session_id}/report-status", json={
            "txn_ref_id": txn_ref_id,
            "txn_status": status,
        })
        if confirmation.get("status") != "confirmed":
            raise IntegrationError("Prava did not confirm the merchant result report")
        for _ in range(4):
            state = await self.payment_state(session_id)
            if state.status == expected_state:
                return state
            if state.status in {"completed", "failed"}:
                raise IntegrationError("Prava final state contradicts the merchant result")
            await asyncio.sleep(0.25)
        raise IntegrationError("Prava accepted the result but its final state is not ready; refresh and retry reporting")

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.secret}"},
                timeout=20,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise IntegrationError("Prava connection failed") from exc
        if response.status_code >= 400:
            response_id = response.headers.get("X-Response-ID")
            suffix = f"; response ID {response_id}" if response_id else ""
            raise IntegrationError(f"Prava rejected the request{suffix}")
        try:
            data = response.json()
        except ValueError as exc:
            raise IntegrationError("Prava returned an unreadable response") from exc
        if not isinstance(data, dict):
            raise IntegrationError("Prava returned an unsupported response")
        return data


class SwiggyBrowserCheckout:
    _number = (
        'input[autocomplete="cc-number"]',
        'input[name*="cardNumber" i]',
        'input[name*="card_number" i]',
        'input[placeholder*="card number" i]',
    )
    _expiry = (
        'input[autocomplete="cc-exp"]',
        'input[name="expiry" i]',
        'input[name="expiryDate" i]',
        'input[placeholder*="/" i]',
    )
    _month = ('input[autocomplete="cc-exp-month"]', 'input[name*="expiryMonth" i]', 'input[name="month" i]')
    _year = ('input[autocomplete="cc-exp-year"]', 'input[name*="expiryYear" i]', 'input[name="year" i]')
    _cvv = (
        'input[autocomplete="cc-csc"]',
        'input[name*="cvv" i]',
        'input[name*="cvc" i]',
        'input[placeholder*="cvv" i]',
        'input[placeholder*="cvc" i]',
    )
    _name = ('input[autocomplete="cc-name"]', 'input[name="name" i]', '[data-testid="cardholder_name"]')
    _declined = re.compile(
        r"payment (?:has )?(?:failed|declined|unsuccessful)|card (?:was )?declined|"
        r"could(?: not|n't) process (?:the )?payment|transaction (?:failed|declined)",
        re.I,
    )
    _approved = re.compile(r"order (?:has been )?(?:placed|confirmed)|order successful|thank you for your order", re.I)

    async def readiness(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=swiggy_cdp_url(),
                timeout=5,
                trust_env=False,
            ) as client:
                response = await client.get("/json/version")
                response.raise_for_status()
                value = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IntegrationError("Swiggy browser CDP readiness failed") from exc
        browser = value.get("Browser")
        if not isinstance(browser, str) or not browser.startswith("Chrome/"):
            raise IntegrationError("Swiggy browser CDP returned an unexpected browser")
        return {
            "connected": True,
            "browser": browser,
            "loopback_only": True,
        }

    @staticmethod
    async def _visible(frames, selectors):
        for frame in frames:
            for selector in selectors:
                locator = frame.locator(selector)
                for index in range(await locator.count()):
                    candidate = locator.nth(index)
                    if await candidate.is_visible():
                        return candidate
        return None

    @staticmethod
    async def _save_checkbox(frames):
        pattern = re.compile(r"save|remember|secure", re.I)
        for frame in frames:
            direct = frame.locator(
                'input[type="checkbox"][name*="save" i], '
                'input[type="checkbox"][name*="remember" i], '
                'input[type="checkbox"][name*="secure" i], '
                '[data-testid="selection-card-tick"]'
            )
            for index in range(await direct.count()):
                candidate = direct.nth(index)
                if await candidate.is_visible():
                    return candidate
            locator = frame.get_by_role("checkbox", name=pattern)
            for index in range(await locator.count()):
                candidate = locator.nth(index)
                if await candidate.is_visible():
                    return candidate
        return None

    @staticmethod
    async def _pay_button(frames):
        pattern = re.compile(r"^(?:pay|place order|proceed)(?:\b|\s|₹)", re.I)
        for frame in frames:
            locator = frame.get_by_role("button", name=pattern)
            for index in range(await locator.count()):
                candidate = locator.nth(index)
                if await candidate.is_visible():
                    return candidate
        return None

    async def _card_form(self, pages):
        for page in reversed(pages):
            frames = page.frames
            number = await self._visible(frames, self._number)
            cvv = await self._visible(frames, self._cvv)
            expiry = await self._visible(frames, self._expiry)
            month = year = None
            if not expiry:
                month = await self._visible(frames, self._month)
                year = await self._visible(frames, self._year)
            name = await self._visible(frames, self._name)
            save = await self._save_checkbox(frames)
            submit = await self._pay_button(frames)
            if number and cvv and (expiry or (month and year)) and save and submit:
                return page, number, cvv, expiry, month, year, name, save, submit
        return None

    async def _open_card_form(self, browser):
        if browser.contexts:
            page = await browser.contexts[0].new_page()
        else:
            raise BrowserCheckoutError("The dedicated Swiggy browser is not available")
        try:
            await page.goto(
                "https://www.swiggy.com/instamart",
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            await page.wait_for_timeout(1_000)
            cart = page.get_by_test_id("review-cart-button")
            if not await cart.count():
                cart = page.get_by_test_id("view-cart-button")
            if not await cart.count() or not await cart.first.is_visible():
                raise BrowserCheckoutError("Max could not find the Swiggy cart in the dedicated browser")
            await cart.first.click(timeout=5_000)
            await page.wait_for_url(re.compile(r"/instamart/cart(?:\?|$)"), timeout=10_000)
            await page.wait_for_timeout(500)
            cart_text = await page.locator("body").inner_text()
            if self._cart_unavailable(cart_text):
                raise BrowserCheckoutError("Swiggy says the selected store or address is currently unavailable")
            checkout = page.get_by_role(
                "button",
                name=re.compile(r"(?:checkout|proceed|continue|pay)", re.I),
            )
            for index in range(await checkout.count()):
                candidate = checkout.nth(index)
                if await candidate.is_visible() and await candidate.is_enabled():
                    await candidate.click(timeout=5_000)
                    break
            else:
                raise BrowserCheckoutError("Max could not find Swiggy's cart checkout action")
            await page.wait_for_url(re.compile(r"/instamart/payment(?:\?|$)"), timeout=10_000)
            await page.wait_for_timeout(500)
            payment_text = (await page.locator("body").inner_text()).lower()
            if "delivering to: null" in payment_text:
                raise BrowserCheckoutError("Swiggy did not carry the selected delivery address into payment")
            if not (form := await self._card_form([page])):
                candidate = page.get_by_role("button", name="Add New Card", exact=True)
                if await candidate.count() and await candidate.is_visible():
                    await candidate.click(timeout=5_000)
                    await page.wait_for_timeout(500)
                form = await self._card_form([page])
        except BrowserCheckoutError:
            raise
        except Exception as exc:
            raise BrowserCheckoutError("Max could not open the Swiggy payment page") from exc
        if not form:
            raise BrowserCheckoutError(
                "Max opened Swiggy but could not find the new-card form; confirm the dedicated browser is logged in"
            )
        return form

    @staticmethod
    async def _just_pay_button(pages):
        pattern = re.compile(r"^just pay$", re.I)
        for page in pages:
            for frame in page.frames:
                locator = frame.get_by_role("button", name=pattern)
                for index in range(await locator.count()):
                    candidate = locator.nth(index)
                    if await candidate.is_visible() and await candidate.is_enabled():
                        return candidate
        return None

    @staticmethod
    async def _page_text(page) -> str:
        chunks = []
        for frame in page.frames:
            try:
                chunks.append(await frame.locator("body").inner_text(timeout=1_000))
            except Exception:
                continue
        return "\n".join(chunks)

    @staticmethod
    async def _clear(locators) -> None:
        for locator in locators:
            try:
                await locator.fill("")
            except Exception:
                pass

    @staticmethod
    def _has_amount(text: str, amount_minor: int) -> bool:
        amount = f"{Decimal(amount_minor) / 100:.2f}"
        whole = amount.removesuffix(".00")
        return bool(re.search(rf"₹\s*{re.escape(whole)}(?:\.00)?\b", text.replace(",", "")))

    @staticmethod
    def _cart_unavailable(text: str) -> bool:
        lowered = text.lower()
        return "unserviceable" in lowered or "store is currently closed" in lowered

    async def checkout(self, quote: Quote, credential: PravaCredential) -> ProviderResult:
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.connect_over_cdp(
                    swiggy_cdp_url(), timeout=5_000, is_local=True, no_defaults=True
                )
                page, number, cvv, expiry, month, year, name, save, submit = await self._open_card_form(browser)

                if not self._has_amount(await self._page_text(page), quote.amount_minor):
                    raise BrowserCheckoutError("The browser total does not match the approved Swiggy quote")
                if name and not (await name.input_value()).strip():
                    try:
                        await name.fill(swiggy_cardholder_name())
                    except Exception as exc:
                        raise BrowserCheckoutError("Max could not fill the configured cardholder name") from exc
                if await save.is_checked():
                    await save.set_checked(False)
                if await save.is_checked():
                    raise BrowserCheckoutError("Swiggy card saving could not be disabled")

                filled = []
                try:
                    await number.fill(credential.token)
                    filled.append(number)
                    if expiry:
                        await expiry.fill(f"{credential.expiry_month.zfill(2)}/{credential.expiry_year[-2:]}")
                        filled.append(expiry)
                    else:
                        await month.fill(credential.expiry_month.zfill(2))
                        await year.fill(credential.expiry_year)
                        filled.extend((month, year))
                    await cvv.fill(credential.dynamic_cvv)
                    filled.append(cvv)
                except Exception as exc:
                    await self._clear(filled)
                    raise BrowserCheckoutError(
                        "Swiggy card fields could not be filled; the checkout was not submitted"
                    ) from exc
                if not await submit.is_enabled():
                    await self._clear(filled)
                    raise BrowserCheckoutError(
                        "Swiggy still requires a manual card field; the checkout was not submitted"
                    )

                # Once this line is crossed, every failure is outcome-unknown and must never auto-retry.
                try:
                    await submit.click()
                    chose_just_pay = False
                    deadline = asyncio.get_running_loop().time() + checkout_timeout_seconds()
                    while asyncio.get_running_loop().time() < deadline:
                        # Only this fresh checkout tab may determine this attempt's result.
                        current_pages = [page]
                        if not chose_just_pay and (just_pay := await self._just_pay_button(current_pages)):
                            await just_pay.click()
                            chose_just_pay = True
                        text = "\n".join([await self._page_text(candidate) for candidate in current_pages])
                        if self._declined.search(text):
                            await self._clear(filled)
                            return ProviderResult(
                                provider="SWIGGY_BROWSER",
                                operation="merchant_checkout",
                                environment=Environment.PRODUCTION,
                                status="DECLINED",
                                terminal=True,
                            )
                        if self._approved.search(text):
                            await self._clear(filled)
                            return ProviderResult(
                                provider="SWIGGY_BROWSER",
                                operation="merchant_checkout",
                                environment=Environment.PRODUCTION,
                                status="APPROVED",
                                terminal=True,
                            )
                        await asyncio.sleep(0.25)
                except Exception:
                    await self._clear(filled)
                    return ProviderResult(
                        provider="SWIGGY_BROWSER",
                        operation="merchant_checkout",
                        environment=Environment.PRODUCTION,
                        status="UNKNOWN",
                        terminal=False,
                        error_class="browser_observation_failed",
                        retry_eligible=False,
                    )
                await self._clear(filled)
                return ProviderResult(
                    provider="SWIGGY_BROWSER",
                    operation="merchant_checkout",
                    environment=Environment.PRODUCTION,
                    status="UNKNOWN",
                    terminal=False,
                    error_class="merchant_result_not_observed",
                    retry_eligible=False,
                )
        except BrowserCheckoutError:
            raise
        except Exception as exc:
            raise BrowserCheckoutError("Swiggy browser checkout was not submitted; correct the browser form and retry") from exc
