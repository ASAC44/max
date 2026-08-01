# Max API

Owns the main agent, deterministic mission workflow, persistence, and external
service adapters. Commerce, payment, notification, and robot simulators must be
clearly labeled and replaced only by observed integrations.

The navigation stack and robot-side backend remain owned by the navigation team.

## Local setup

From this directory:

```bash
uv sync --extra dev
cp ../../.env.example ../../.env
```

Initialize and run with that environment file:

```bash
uv run --env-file ../../.env alembic upgrade head
uv run --env-file ../../.env uvicorn max_api.main:app --host 127.0.0.1 --port 8000
```

The default `MAX_AGENT_MODE=simulated` is intentionally labeled. To run the
real text interpreter, set `MAX_AGENT_MODE=openai`, `OPENAI_API_KEY`, and an
explicit `OPENAI_MODEL`. The model ID used is evidence, not a final model
decision. The OpenAI agent has no payment, checkout, cancellation, staged, or
robot tools. Responses are configured with `store=False`, and sensitive trace
payload capture is disabled. `OPENAI_REQUEST_TIMEOUT_SECONDS` bounds the model
call at the application layer and defaults to 30 seconds.

Commerce and payment are independently selectable:

```env
MAX_COMMERCE_MODE=swiggy
MAX_PAYMENT_MODE=prava
PRAVA_SECRET_KEY=sk_test_...
PRAVA_USER_ID=max-demo-owner
PRAVA_USER_EMAIL=owner@example.com
PRAVA_CALLBACK_URL=https://your-public-host/payment-done
```

Swiggy live mode starts the verified Instamart sequence through `mcp-remote`:
saved address, product search, an empty-cart check, cart update, and a fresh
quote. The first run opens Swiggy OAuth in the local browser. Raw address/cart
responses stay in process; only the address label, selected product, variant,
quantity, total, and fee summary enter mission state.

Prava live mode creates a hosted sandbox session only after exact-quote
approval. The returned approval URL appears as `payment_action`. Call
`refresh-payment` after the owner completes hosted verification; the API stores
only the Prava state, transaction reference, and whether all credential fields
were present. It never returns or persists the network token, expiry, or
dynamic CVV.

Point `PRAVA_CALLBACK_URL` at the public HTTPS form of
`/api/payments/prava/complete`. The route changes no state; after returning,
the authenticated operator explicitly calls `refresh-payment`.

This is intentionally not a completed Swiggy checkout adapter. The observed
Swiggy browser cart/card handoff still needs a deterministic credential-entry
bridge, and the current manual run is blocked by Prava's hosted
`Verification Unavailable` screen. Until that is cleared, live mode stops safely
at payment readiness and must not be described as end to end.

## Checks

```bash
uv run pytest -q
uv run alembic check
```

The API binds to loopback by default. Every mission route requires
`Authorization: Bearer $MAX_ADMIN_TOKEN`; mutation commands also require a fresh
mission version and an idempotency key. The operator token must be a non-default
value of at least 24 characters. SQLite/SQLAlchemy is authoritative.
