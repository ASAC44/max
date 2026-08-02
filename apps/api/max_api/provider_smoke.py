from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from urllib.parse import urlparse

from .integrations import PravaClient
from .models import utcnow
from .schemas import Environment, Quote, QuoteLine


async def create_prava_session() -> None:
    client = PravaClient()
    if client.environment != "sandbox":
        raise RuntimeError("prava-session smoke is sandbox-only")
    quote = Quote(
        revision=1,
        merchant="SWIGGY_INSTAMART",
        product_name="Max sandbox readiness item",
        variant_id="sandbox-readiness",
        quantity=1,
        amount_minor=100,
        currency="INR",
        destination="sandbox",
        environment=Environment.PRODUCTION,
        expires_at=utcnow() + timedelta(minutes=15),
        line_items=[
            QuoteLine(
                description="Max sandbox readiness item",
                unit_price_minor=100,
                quantity=1,
            )
        ],
    )
    session = await client.create_session(quote)
    print(
        json.dumps(
            {
                "status": "ok",
                "provider": "PRAVA",
                "environment": client.environment,
                "approval_host": urlparse(session.approval_url).hostname,
                "expires_at": session.expires_at,
                "money_moved": False,
            },
            separators=(",", ":"),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run explicit redacted provider sandbox checks"
    )
    parser.add_argument(
        "check",
        choices=["prava-session"],
        help="the sandbox check to run",
    )
    args = parser.parse_args()
    if args.check == "prava-session":
        asyncio.run(create_prava_session())


if __name__ == "__main__":
    main()
