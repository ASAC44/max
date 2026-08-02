from __future__ import annotations

import argparse
from urllib.parse import urlparse

import httpx

from .config import telegram_bot_token, telegram_webhook_secret


def call(method: str, payload: dict | None = None) -> dict:
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{telegram_bot_token()}/{method}",
            json=payload or {},
            timeout=20,
            trust_env=False,
        )
        body = response.json()
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise SystemExit("Telegram setup request failed") from exc
    if response.status_code != 200 or not body.get("ok"):
        raise SystemExit("Telegram rejected the setup request")
    return body


def discover() -> None:
    updates = call("getUpdates", {"allowed_updates": ["message"]}).get("result", [])
    found: set[tuple[int, int, str]] = set()
    for update in updates:
        message = update.get("message", {})
        sender = message.get("from", {})
        chat = message.get("chat", {})
        user_id, chat_id = sender.get("id"), chat.get("id")
        if isinstance(user_id, int) and isinstance(chat_id, int):
            found.add((user_id, chat_id, str(chat.get("type", "unknown"))))
    if not found:
        print("No messages found. Send /start to the bot, then run discover again.")
        return
    for user_id, chat_id, chat_type in sorted(found):
        print(f"user_id={user_id} chat_id={chat_id} chat_type={chat_type}")


def set_webhook(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SystemExit("Webhook URL must be a public HTTPS URL")
    if not parsed.path.endswith("/api/integrations/telegram/webhook"):
        raise SystemExit("Webhook URL must end with /api/integrations/telegram/webhook")
    call(
        "setWebhook",
        {
            "url": url,
            "secret_token": telegram_webhook_secret(),
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        },
    )
    print("Telegram webhook configured.")


def status() -> None:
    info = call("getWebhookInfo").get("result", {})
    print(f"url={info.get('url', '')}")
    print(f"pending_update_count={info.get('pending_update_count', 0)}")
    if info.get("last_error_message"):
        print(f"last_error={info['last_error_message']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure the Max Telegram webhook safely")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("discover")
    configure = subcommands.add_parser("set")
    configure.add_argument("--url", required=True)
    subcommands.add_parser("status")
    args = parser.parse_args()
    if args.command == "discover":
        discover()
    elif args.command == "set":
        set_webhook(args.url)
    else:
        status()


if __name__ == "__main__":
    main()
