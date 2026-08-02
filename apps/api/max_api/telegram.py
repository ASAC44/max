from __future__ import annotations

import asyncio
import hmac
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import (
    admin_token,
    telegram_auto_checkout,
    telegram_bot_token,
    telegram_control_api_url,
    telegram_owner_user_id,
    telegram_worker_interval_seconds,
)
from .db import SessionLocal
from .models import Mission, TelegramNotification, TelegramUpdate, utcnow


class TelegramError(RuntimeError):
    """Safe Telegram/control-plane error with no provider response content."""


@dataclass(frozen=True)
class TelegramInbound:
    update_id: int
    kind: str
    chat_id: int
    user_id: int
    request_text: str | None = None
    callback_query_id: str | None = None
    callback_data: str | None = None


def parse_telegram_update(payload: dict[str, Any]) -> TelegramInbound | None:
    update_id = payload.get("update_id")
    if not isinstance(update_id, int) or update_id < 0:
        raise TelegramError("Telegram update_id is invalid")

    message = payload.get("message")
    if isinstance(message, dict):
        sender = message.get("from")
        chat = message.get("chat")
        text = message.get("text")
        if not isinstance(sender, dict) or not isinstance(chat, dict) or not isinstance(text, str):
            return None
        user_id, chat_id = sender.get("id"), chat.get("id")
        if not isinstance(user_id, int) or not isinstance(chat_id, int):
            return None
        if len(text) > 2000:
            raise TelegramError("Telegram message is too long")
        return TelegramInbound(update_id, "message", chat_id, user_id, request_text=text.strip())

    callback = payload.get("callback_query")
    if isinstance(callback, dict):
        sender = callback.get("from")
        message = callback.get("message")
        chat = message.get("chat") if isinstance(message, dict) else None
        query_id, data = callback.get("id"), callback.get("data")
        user_id = sender.get("id") if isinstance(sender, dict) else None
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        if (
            not isinstance(user_id, int)
            or not isinstance(chat_id, int)
            or not isinstance(query_id, str)
            or not isinstance(data, str)
        ):
            return None
        if len(data) > 128:
            raise TelegramError("Telegram callback data is too long")
        return TelegramInbound(
            update_id,
            "callback",
            chat_id,
            user_id,
            callback_query_id=query_id,
            callback_data=data,
        )
    return None


def enqueue_telegram_update(session: Session, inbound: TelegramInbound) -> bool:
    session.add(
        TelegramUpdate(
            update_id=inbound.update_id,
            kind=inbound.kind,
            chat_id=inbound.chat_id,
            user_id=inbound.user_id,
            request_text=inbound.request_text,
            callback_query_id=inbound.callback_query_id,
            callback_data=inbound.callback_data,
            status="PENDING",
            attempts=0,
        )
    )
    try:
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False


class TelegramClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=f"https://api.telegram.org/bot{telegram_bot_token()}",
                transport=self.transport,
                timeout=15,
                trust_env=False,
            ) as client:
                response = await client.post(f"/{method}", json=payload)
        except (httpx.HTTPError, RuntimeError) as exc:
            raise TelegramError("Telegram API connection failed") from exc
        if response.status_code != 200:
            raise TelegramError("Telegram API rejected the request")
        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramError("Telegram API returned an invalid response") from exc
        if not body.get("ok"):
            raise TelegramError("Telegram API rejected the request")
        return body

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:4096],
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        await self._call("sendMessage", payload)

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        await self._call(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text[:200]},
        )


class ControlApiClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        token = admin_token()
        if not token:
            raise TelegramError("MAX_ADMIN_TOKEN is not configured")
        request_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
        try:
            async with httpx.AsyncClient(
                base_url=telegram_control_api_url(),
                transport=self.transport,
                timeout=120,
                trust_env=False,
            ) as client:
                response = await client.request(method, path, headers=request_headers, json=json)
        except (httpx.HTTPError, RuntimeError) as exc:
            raise TelegramError("Max control API connection failed") from exc
        if response.status_code == 404 and path == "/api/missions/active":
            return None
        if response.status_code not in {200, 201}:
            reason = "Max control API rejected the request"
            if response.status_code in {409, 502}:
                try:
                    detail = response.json().get("detail")
                except (AttributeError, ValueError):
                    detail = None
                message = detail.get("message") if isinstance(detail, dict) else None
                if (
                    isinstance(message, str)
                    and 1 <= len(message.strip()) <= 300
                    and all(character.isprintable() for character in message)
                ):
                    reason = message.strip()
            raise TelegramError(reason)
        try:
            return response.json()
        except ValueError as exc:
            raise TelegramError("Max control API returned an invalid response") from exc


def _format_amount(amount_minor: int, currency: str) -> str:
    if currency == "INR":
        return f"₹{amount_minor / 100:,.2f}"
    return f"{currency} {amount_minor / 100:,.2f}"


def _help_message() -> str:
    return (
        "Hi! Send me one complete order request containing:\n"
        "• item and quantity\n"
        "• maximum total budget, including fees\n"
        "• your saved Swiggy address label\n\n"
        "Example:\n"
        "Order 1 packet of Parle-G biscuits, maximum total ₹150 including all fees, "
        "to my saved Home address. No substitutions and no tip.\n\n"
        "I will fetch the live Swiggy cart total and show it to you first. "
        "The order can proceed only after you approve that exact amount in Prava.\n\n"
        "Commands: /status, /cancel, /help"
    )


def _failure_message(exc: Exception) -> str:
    if not isinstance(exc, TelegramError):
        return (
            "Something unexpected went wrong while processing your request.\n\n"
            "No checkout or payment was attempted. Please use /status before trying again."
        )
    reason = str(exc).strip()
    normalized = reason.casefold()
    if "exceeds the owner's maximum budget" in normalized:
        return (
            "The live Swiggy cart total is above the maximum budget you gave me.\n\n"
            "No checkout or payment was attempted. Reply with a higher maximum total "
            "budget, including all fees, or choose a different item."
        )
    if "oauth" in normalized or "complete oauth setup" in normalized:
        return (
            "I could not access the connected Swiggy account because its login session "
            "needs attention.\n\nNo checkout or payment was attempted. Reconnect Swiggy, "
            "then send the same request again."
        )
    if "no saved swiggy address matches" in normalized:
        return (
            "I could not find that saved Swiggy address label.\n\n"
            "No checkout or payment was attempted. Reply with the exact saved label, "
            "for example Home or Work."
        )
    if "no purchasable result" in normalized:
        return (
            "Swiggy did not return an available product for that request.\n\n"
            "No checkout or payment was attempted. Try a more specific product name "
            "or allow a substitute."
        )
    if "not serviceable" in normalized:
        return (
            "Swiggy says that address is not serviceable right now.\n\n"
            "No checkout or payment was attempted. Choose another saved address or try later."
        )
    return (
        f"I could not complete the request:\n\n{reason}\n\n"
        "No checkout or payment was attempted. Correct the request and send it again."
    )


def mission_message(mission: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    phase = mission["phase"]
    mission_id = mission["id"]
    version = mission["version"]
    if phase == "NEEDS_CLARIFICATION":
        return (
            "I need a little more information before I can check Swiggy:\n\n"
            f"{mission['clarification_question']}\n\n"
            "Reply in this chat with the missing details. Nothing has been ordered or paid for.",
            None,
        )
    quote = mission.get("quote")
    if phase == "PAYMENT_APPROVAL_REQUIRED" and quote and mission.get("payment_action"):
        amount = _format_amount(quote["amount_minor"], quote["currency"])
        text = (
            "Live Swiggy quote ready\n\n"
            f"Item: {quote['product_name']}\n"
            f"Quantity: {quote['quantity']}\n"
            f"Total: {amount}\n"
            f"Destination: {quote['destination']}\n\n"
            "Review the item, address, and total carefully. Tap the Prava button to approve "
            "this exact amount, or cancel the order. "
            "No payment or checkout happens until you approve it."
        )
        buttons = {
            "inline_keyboard": [
                [{"text": f"Approve {amount} in Prava", "url": mission["payment_action"]["approval_url"]}],
                [{"text": "Cancel order", "callback_data": f"cancel:{mission_id}:{version}"}],
            ]
        }
        return text, buttons
    if phase == "PAYMENT_PERMISSION_READY":
        if not telegram_auto_checkout():
            return (
                "Prava sandbox approval received and recorded. Automatic Swiggy checkout "
                "is disabled, so no merchant order or payment will be submitted. "
                "Use /status for the latest state.",
                None,
            )
        return (
            "Prava approval received. I am verifying that the Swiggy cart still matches "
            "the amount you approved before checkout. Use /status for the latest result.",
            None,
        )
    if phase == "ORDER_CONFIRMED":
        if mission.get("environment") == "staged_demo":
            status = mission.get("commerce_status", "SOURCE_ORDER_CONFIRMED")
            return (
                f"Staged pickup created from status: {status}. "
                "Confirm only after the physical package is actually ready.",
                {
                    "inline_keyboard": [[{
                        "text": "Confirm package ready",
                        "callback_data": f"package:{mission_id}:{version}",
                    }]]
                },
            )
        status = mission.get("commerce_status", "ORDER_CONFIRMED")
        return (
            f"Order confirmed by Swiggy.\n\nCurrent status: {status}\n\n"
            "I will keep forwarding order updates to the bot. Use /status anytime. "
            "Physical pickup remains a separate staged workflow until live autonomous "
            "motion is explicitly enabled and validated.",
            {
                "inline_keyboard": [[{
                    "text": "Start staged pickup",
                    "callback_data": f"stage:{mission_id}:{version}",
                }]]
            },
        )
    if phase == "PAYMENT_DECLINED":
        return (
            "Payment was declined and no order was placed. You may still run the explicitly staged pickup rehearsal.",
            {
                "inline_keyboard": [[{
                    "text": "Start staged rehearsal",
                    "callback_data": f"stage:{mission_id}:{version}",
                }]]
            },
        )
    if phase == "READY_TO_DISPATCH":
        if mission.get("robot_job"):
            job = mission["robot_job"]
            return (
                f"Pi job {job['status'].lower()} from {job['trigger_source'].lower()} "
                f"status {job['trigger_status']}. Motor motion remains disabled.",
                None,
            )
        return (
            "Package-ready gate recorded. The Pi job remains dry-run and cannot start motor motion.",
            {
                "inline_keyboard": [[{
                    "text": "Send dry-run job",
                    "callback_data": f"dispatch:{mission_id}:{version}",
                }]]
            },
        )
    if phase == "AT_PICKUP":
        return "Pi rehearsal reached the pickup checkpoint; motors remained disabled.", None
    if phase == "ITEM_SECURED":
        return "Staged item-secured checkpoint recorded; motors remained disabled.", None
    if phase == "RETURNING":
        return "Pi rehearsal entered the return checkpoint; motors remained disabled.", None
    if phase == "COMPLETED":
        return "Staged pickup-and-return rehearsal completed with physical motion disabled.", None
    if phase in {"CANCELLED", "CLOSED_UNRESOLVED", "CHECKOUT_OUTCOME_UNKNOWN"}:
        return f"Mission stopped with status: {phase}. No robot dispatch was started.", None
    return f"Mission status: {phase}.", None


class TelegramWorker:
    def __init__(
        self,
        *,
        telegram: TelegramClient | None = None,
        control: ControlApiClient | None = None,
    ):
        self.telegram = telegram or TelegramClient()
        self.control = control or ControlApiClient()
        self.owner_chat_id: int | None = telegram_owner_user_id()

    def recover(self) -> None:
        with SessionLocal() as session:
            session.execute(
                update(TelegramUpdate)
                .where(TelegramUpdate.status == "PROCESSING")
                .values(status="PENDING", error_class=None)
            )
            session.commit()

    def _claim(self) -> TelegramUpdate | None:
        with SessionLocal() as session:
            row = session.scalar(
                select(TelegramUpdate)
                .where(TelegramUpdate.status == "PENDING")
                .order_by(TelegramUpdate.created_at, TelegramUpdate.update_id)
                .limit(1)
            )
            if not row:
                return None
            row.status = "PROCESSING"
            row.attempts += 1
            session.commit()
            session.expunge(row)
            return row

    def _finish(
        self,
        update_id: int,
        *,
        status: str,
        mission_id: str | None = None,
        error_class: str | None = None,
    ) -> None:
        with SessionLocal() as session:
            row = session.get(TelegramUpdate, update_id)
            if not row:
                return
            row.status = status
            row.mission_id = mission_id
            row.error_class = error_class
            row.processed_at = utcnow() if status == "DONE" else None
            session.commit()

    async def _active(self) -> dict[str, Any] | None:
        return await self.control.request("GET", "/api/missions/active")

    async def _send_mission(self, chat_id: int, mission: dict[str, Any]) -> None:
        text, markup = mission_message(mission)
        await self.telegram.send_message(chat_id, text, reply_markup=markup)

    async def _process_message(self, row: TelegramUpdate) -> str | None:
        text = (row.request_text or "").strip()
        if text in {"/start", "/help"}:
            await self.telegram.send_message(row.chat_id, _help_message())
            return None
        if text.casefold() in {"hi", "hello", "hey", "hi max", "hello max"}:
            await self.telegram.send_message(row.chat_id, _help_message())
            return None
        active = await self._active()
        if text == "/status":
            if active:
                await self._send_mission(row.chat_id, active)
                return active["id"]
            await self.telegram.send_message(
                row.chat_id,
                "There is no active order. Send a complete order request whenever you are ready. "
                "Use /help for an example.",
            )
            return None
        if text == "/cancel":
            if not active:
                await self.telegram.send_message(row.chat_id, "There is no active order to cancel.")
                return None
            mission = await self.control.request(
                "POST",
                f"/api/missions/{active['id']}/commands/cancel",
                json={
                    "expected_version": active["version"],
                    "command_id": f"tg-cancel-{row.update_id}",
                },
            )
            if mission:
                await self._send_mission(row.chat_id, mission)
            return active["id"]
        if not text or text.startswith("/"):
            await self.telegram.send_message(
                row.chat_id,
                "I do not recognize that command. Available commands: /status, /cancel, /help.",
            )
            return None
        if active and active["phase"] == "NEEDS_CLARIFICATION":
            mission = await self.control.request(
                "POST",
                f"/api/missions/{active['id']}/commands/reply",
                json={
                    "text": text,
                    "expected_version": active["version"],
                    "command_id": f"tg-reply-{row.update_id}",
                },
            )
        elif active:
            await self.telegram.send_message(
                row.chat_id,
                f"A mission is already active ({active['phase']}). Use /status or its Cancel button first.",
            )
            return active["id"]
        else:
            mission = await self.control.request(
                "POST",
                "/api/missions",
                headers={"Idempotency-Key": f"tg-create-{row.update_id}"},
                json={"text": text},
            )
        if mission is None:
            raise TelegramError("Max control API returned no mission")
        await self._send_mission(row.chat_id, mission)
        return mission["id"]

    async def _process_callback(self, row: TelegramUpdate) -> str | None:
        parts = (row.callback_data or "").split(":")
        if len(parts) != 3 or parts[0] not in {
            "cancel",
            "stage",
            "package",
            "dispatch",
        }:
            if row.callback_query_id:
                await self.telegram.answer_callback(row.callback_query_id, "This action is no longer valid.")
            return None
        action, mission_id, version_text = parts
        try:
            version = int(version_text)
        except ValueError as exc:
            raise TelegramError("Telegram callback version is invalid") from exc
        route_by_action = {
            "cancel": "cancel",
            "stage": "start-staged",
            "package": "package-ready",
            "dispatch": "run-robot",
        }
        mission = await self.control.request(
            "POST",
            f"/api/missions/{mission_id}/commands/{route_by_action[action]}",
            json={
                "expected_version": version,
                "command_id": f"tg-{action}-{row.update_id}",
            },
        )
        if row.callback_query_id:
            callback_text = {
                "cancel": "Order cancelled.",
                "stage": "Staged pickup created.",
                "package": "Package-ready gate recorded.",
                "dispatch": "Dry-run job sent.",
            }[action]
            await self.telegram.answer_callback(row.callback_query_id, callback_text)
        if mission:
            await self._send_mission(row.chat_id, mission)
        return mission_id

    async def process_one(self) -> bool:
        row = self._claim()
        if not row:
            return False
        try:
            if row.kind == "message":
                mission_id = await self._process_message(row)
            elif row.kind == "callback":
                mission_id = await self._process_callback(row)
            else:
                raise TelegramError("Unsupported Telegram update kind")
        except Exception as exc:
            self._finish(
                row.update_id,
                status="FAILED",
                error_class=type(exc).__name__,
            )
            try:
                await self.telegram.send_message(
                    row.chat_id,
                    _failure_message(exc),
                )
            except TelegramError:
                pass
            return True
        self._finish(row.update_id, status="DONE", mission_id=mission_id)
        return True

    def _reserve_notification(self, mission: dict[str, Any], chat_id: int, kind: str) -> bool:
        with SessionLocal() as session:
            session.add(
                TelegramNotification(
                    mission_id=mission["id"],
                    mission_version=mission["version"],
                    kind=kind,
                    chat_id=chat_id,
                )
            )
            try:
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                return False

    def _release_notification(
        self,
        mission: dict[str, Any],
        chat_id: int,
        kind: str,
    ) -> None:
        with SessionLocal() as session:
            session.execute(
                delete(TelegramNotification).where(
                    TelegramNotification.mission_id == mission["id"],
                    TelegramNotification.mission_version == mission["version"],
                    TelegramNotification.kind == kind,
                    TelegramNotification.chat_id == chat_id,
                )
            )
            session.commit()

    async def _send_reserved_notification(
        self,
        mission: dict[str, Any],
        chat_id: int,
        kind: str,
    ) -> bool:
        if not self._reserve_notification(mission, chat_id, kind):
            return False
        try:
            await self._send_mission(chat_id, mission)
        except Exception:
            self._release_notification(mission, chat_id, kind)
            raise
        return True

    async def advance_payment(self) -> None:
        mission = await self._active()
        if not mission:
            return
        if mission["phase"] == "PAYMENT_APPROVAL_REQUIRED":
            mission = await self.control.request(
                "POST",
                f"/api/missions/{mission['id']}/commands/refresh-payment",
                json={
                    "expected_version": mission["version"],
                    "command_id": f"tg-refresh-{mission['id'][:8]}-{mission['version']}",
                },
            )
        if mission and mission["phase"] == "PAYMENT_PERMISSION_READY":
            if self.owner_chat_id:
                await self._send_reserved_notification(
                    mission,
                    self.owner_chat_id,
                    "payment_ready",
                )
            if not telegram_auto_checkout():
                return
            mission = await self.control.request(
                "POST",
                f"/api/missions/{mission['id']}/commands/execute-checkout",
                json={
                    "expected_version": mission["version"],
                    "command_id": f"tg-checkout-{mission['id'][:8]}-{mission['version']}",
                },
            )
            if mission and self.owner_chat_id:
                await self._send_reserved_notification(
                    mission,
                    self.owner_chat_id,
                    "checkout",
                )

    async def notify_fulfilment(self) -> None:
        if not self.owner_chat_id:
            return
        with SessionLocal() as session:
            mission_id = session.scalar(
                select(Mission.id)
                .where(
                    Mission.environment == "staged_demo",
                    Mission.phase.in_(
                        ("AT_PICKUP", "ITEM_SECURED", "RETURNING", "COMPLETED")
                    ),
                )
                .order_by(Mission.updated_at.desc())
                .limit(1)
            )
        if not mission_id:
            return
        mission = await self.control.request("GET", f"/api/missions/{mission_id}")
        if mission:
            await self._send_reserved_notification(
                mission,
                self.owner_chat_id,
                "fulfilment",
            )

    async def notify_order_status(self) -> None:
        if not self.owner_chat_id:
            return
        with SessionLocal() as session:
            mission_id = session.scalar(
                select(Mission.id)
                .where(
                    Mission.environment == "production",
                    Mission.phase == "ORDER_CONFIRMED",
                    Mission.commerce_status.like("SWIGGY_%"),
                )
                .order_by(Mission.updated_at.desc())
                .limit(1)
            )
        if not mission_id:
            return
        mission = await self.control.request(
            "GET",
            f"/api/missions/{mission_id}",
        )
        if mission:
            await self._send_reserved_notification(
                mission,
                self.owner_chat_id,
                "swiggy_status",
            )

    async def run(self) -> None:
        self.recover()
        interval = telegram_worker_interval_seconds()
        while True:
            processed = await self.process_one()
            try:
                await self.advance_payment()
                await self.notify_order_status()
                await self.notify_fulfilment()
            except TelegramError:
                pass
            if not processed:
                await asyncio.sleep(interval)


def verify_telegram_owner(user_id: int) -> bool:
    return hmac.compare_digest(str(user_id), str(telegram_owner_user_id()))


def main() -> None:
    asyncio.run(TelegramWorker().run())
