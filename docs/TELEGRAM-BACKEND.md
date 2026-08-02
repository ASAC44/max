# Telegram backend and outbound Pi control

## What this deployment does

The backend accepts a private Telegram message, turns it into a Max mission,
obtains a Swiggy quote, and sends the exact item, quantity, total, and
destination back to Telegram. Checkout remains blocked until the owner opens
the one-time Prava link and completes verification.

When `MAX_TELEGRAM_AUTO_CHECKOUT=true`, the worker observes that exact Prava
permission and submits the matching Swiggy checkout once. A plain Telegram
message is never sufficient authority to spend money.

The Pi connects outbound to the backend. It does not require a public IP,
router port forwarding, or an inbound tunnel. The unified Pi agent sends
heartbeats, resumes an interrupted staged job, reports the staged pickup
lifecycle, and explicitly refuses wheel motion.

## Recommended topology

Use one persistent Linux VM, not a serverless function:

```text
Telegram -> HTTPS reverse proxy -> Max API + SQLite volume
                                      |
                                      +-> Telegram worker
                                      +-> Swiggy MCP OAuth
                                      +-> logged-in Chrome on :9222
                                      +-> Prava sandbox or production

Raspberry Pi -> outbound HTTPS polling -> Max API
```

The persistent VM is required because Swiggy MCP OAuth and the final checkout
browser use durable per-user state. The dedicated Chrome profile must remain
logged in. Run only one API replica and one worker while SQLite is used.

## Required values

In `.env`, retain the existing OpenAI, Swiggy, and Prava settings and add:

```env
TELEGRAM_BOT_TOKEN=from-BotFather
TELEGRAM_WEBHOOK_SECRET=a-random-24-to-128-character-secret
TELEGRAM_OWNER_USER_ID=your-numeric-private-chat-user-id
MAX_CONTROL_API_URL=http://127.0.0.1:8000
MAX_TELEGRAM_WORKER_INTERVAL_SECONDS=5
MAX_TELEGRAM_AUTO_CHECKOUT=false
PRAVA_ENVIRONMENT=sandbox

MAX_ROBOT_MODE=pi_poll
MAX_ROBOT_TOKEN=a-separate-random-secret-at-least-24-characters
MAX_ROBOT_DRY_RUN=true
```

Do not put these values in Git, chat, screenshots, or a public deployment
manifest.

## Telegram setup

1. Create a bot through BotFather and put its token only in `.env`.
2. Send `/start` to the new bot in a private chat.
3. Before setting a webhook, discover the numeric owner ID:

   ```bash
   cd apps/api
   .venv/bin/python -m max_api.telegram_setup discover
   ```

4. Set `TELEGRAM_OWNER_USER_ID` to the `user_id` where `chat_type=private`.
5. Give the API a stable public HTTPS address.
6. Register the webhook:

   ```bash
   cd apps/api
   .venv/bin/python -m max_api.telegram_setup set \
     --url https://max.example.com/api/integrations/telegram/webhook
   ```

7. Check delivery state:

   ```bash
   cd apps/api
   .venv/bin/python -m max_api.telegram_setup status
   ```

The webhook verifies Telegram's secret-token header, accepts only the configured
private-chat owner, and deduplicates `update_id` before returning success.

## Persistent Linux VM

Install a TLS reverse proxy such as Caddy or Nginx and expose only the API
through HTTPS. Keep the raw Uvicorn port and Chrome CDP port bound to loopback.

Start a dedicated logged-in Chrome process on the VM:

```bash
google-chrome-stable --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.local/share/max-swiggy-browser"
```

Complete Swiggy login and MCP OAuth interactively once. Then start the API and
worker:

```bash
docker compose -f docker-compose.control.yml up -d --build
```

The compose file uses Linux host networking so the API can reach the dedicated
Chrome loopback port. It also runs the production dashboard and a Caddy HTTPS
proxy using `MAX_PUBLIC_HOST`. It is not intended for a multi-replica
deployment.

Keep `MAX_TELEGRAM_AUTO_CHECKOUT=false` through these dry-runs:

1. `/help` returns usage.
2. `/status` reports no mission.
3. An incomplete request asks for clarification.
4. A complete request returns an exact quote and Prava link.
5. Cancel stops the mission.
6. No Swiggy checkout was submitted.

Only after those checks and a deliberate real-order rehearsal should
`MAX_TELEGRAM_AUTO_CHECKOUT` be changed to `true`.

## Prava environments

`PRAVA_ENVIRONMENT=sandbox` requires an `sk_test_*` key and uses
`https://sandbox.api.prava.space`. `PRAVA_ENVIRONMENT=production` requires an
`sk_live_*` key and uses `https://api.prava.space`. A prefix/environment
mismatch fails closed during client construction. Production access is
separately enabled by Prava after its go-live verification; changing this
setting does not grant production access.

The merchant checkout kill switch remains independent:
`MAX_PURCHASE_ENABLED=false` blocks submission in either payment environment.
Keep it false for Telegram, quote, hosted-approval, decline, expiry, and
revocation tests. A production checkout also requires an exact owner-approved
quote and a single-use Prava permission.

## Unified Pi agent

Use the installer and bundle described in
[UNIFIED-RUNTIME.md](UNIFIED-RUNTIME.md). Its protected environment contains:

```env
MAX_CONTROL_API_URL=https://max.example.com
MAX_ROBOT_TOKEN=the-same-separate-robot-secret
MAX_ROBOT_POLL_INTERVAL_SECONDS=5
MAX_ROBOT_HEARTBEAT_INTERVAL_SECONDS=10
MAX_ROBOT_DRY_RUN=true
MAX_ROBOT_REHEARSAL=false
```

The dashboard and Telegram show the same staged lifecycle truth. Set
`MAX_ROBOT_DRY_RUN=false` only after completing the physical commissioning and
acceptance procedure in [PHYSICAL-ROBOT-DEMO.md](PHYSICAL-ROBOT-DEMO.md).
