import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from .models import utcnow
from .schemas import Environment, Quote, QuoteLine, ShoppingIntent


class IntegrationError(RuntimeError):
    """A safe external-integration error whose message contains no provider data."""


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

    async def quote(self, intent: ShoppingIntent) -> Quote:
        server = StdioServerParameters(
            command="npx",
            args=["--yes", "mcp-remote", self.endpoint],
        )
        try:
            async with stdio_client(server, errlog=subprocess.DEVNULL) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                    required = {"get_addresses", "search_products", "update_cart", "get_cart"}
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
                        raise IntegrationError("Swiggy cart must be empty before starting a Max mission")

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
                    total = self._cart_total(cart)
        except IntegrationError:
            raise
        except Exception as exc:
            raise IntegrationError("Swiggy MCP connection failed; complete OAuth setup and retry") from exc

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

    @staticmethod
    def _select_address(payload: dict[str, Any], destination: str) -> dict[str, Any]:
        addresses = _list(payload, "addresses")
        if not addresses:
            raise IntegrationError("Swiggy account has no saved serviceable address")
        wanted = "work" if destination.lower() == "office" else destination.lower()
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


class PravaClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.secret = os.getenv("PRAVA_SECRET_KEY", "")
        self.user_id = os.getenv("PRAVA_USER_ID", "")
        self.user_email = os.getenv("PRAVA_USER_EMAIL", "")
        self.callback_url = os.getenv("PRAVA_CALLBACK_URL", "")
        self.transport = transport
        if not self.secret.startswith("sk_test_"):
            raise IntegrationError("PRAVA_SECRET_KEY must be a sandbox sk_test key")
        if not self.user_id or not self.user_email:
            raise IntegrationError("PRAVA_USER_ID and PRAVA_USER_EMAIL are required")
        if urlparse(self.callback_url).scheme != "https":
            raise IntegrationError("PRAVA_CALLBACK_URL must be HTTPS for hosted checkout")

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
            "callback_url": self.callback_url,
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
        if parsed.scheme != "https" or parsed.hostname != "sandbox.collect.prava.space":
            raise IntegrationError("Prava returned an unexpected sandbox approval URL")
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

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url="https://sandbox.api.prava.space",
                headers={"Authorization": f"Bearer {self.secret}"},
                timeout=20,
                transport=self.transport,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise IntegrationError("Prava sandbox connection failed") from exc
        if response.status_code >= 400:
            response_id = response.headers.get("X-Response-ID")
            suffix = f"; response ID {response_id}" if response_id else ""
            raise IntegrationError(f"Prava sandbox rejected the request{suffix}")
        try:
            data = response.json()
        except ValueError as exc:
            raise IntegrationError("Prava returned an unreadable response") from exc
        if not isinstance(data, dict):
            raise IntegrationError("Prava returned an unsupported response")
        return data
