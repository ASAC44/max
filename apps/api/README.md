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
PRAVA_CALLBACK_URL=
SWIGGY_CDP_URL=http://127.0.0.1:9222
SWIGGY_CARDHOLDER_NAME=Your Name
MAX_ROBOT_BASE_URL=http://127.0.0.1:8080
MAX_ROBOT_OPERATOR_PIN=change-me
MAX_ROBOT_OUTBOUND_SECONDS=30
MAX_DISPATCH_BUFFER_SECONDS=60
```

Swiggy live mode starts the verified Instamart sequence through `mcp-remote`:
saved address, product search, an empty-cart check, cart update, and a fresh
quote. The first run opens Swiggy OAuth in the local browser. Raw address/cart
responses stay in process; only the address label, selected product, variant,
quantity, total, and fee summary enter mission state.

Prava live mode creates a hosted sandbox session for the immutable live quote.
The returned approval URL appears as `payment_action`; approval inside Prava is
the sole live payment checkpoint. The dashboard polls Prava automatically and
stores only the state, transaction reference, and whether all credential fields
were present. It never returns or persists the network token, expiry, or dynamic
CVV.

`PRAVA_CALLBACK_URL` is optional. If set, point it at the public HTTPS form of
`/api/payments/prava/complete`; the landing page tells the owner that Max will
continue. The dashboard performs the actual status polling in either case.

For the final merchant attempt, start a separate Chromium profile before the
API and log it into the same Swiggy account once:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/max-swiggy-browser
```

Chrome 136+ ignores remote debugging against its default profile, so the
separate `--user-data-dir` is required. `SWIGGY_CDP_URL` accepts loopback HTTP
only because this endpoint controls the attached browser.

After Prava approval, the dashboard automatically detects
`PAYMENT_PERMISSION_READY` and invokes the one-shot checkout. The API then:

1. re-reads the Swiggy MCP cart and checks variant, quantity, and exact total;
2. fetches the scoped Prava credential into memory only;
3. opens the Instamart payment page, selects the new-card form when needed,
   fills the configured cardholder name, confirms the total, and disables card
   saving;
4. fills and submits the card form once;
5. classifies a visible decline or order confirmation; and
6. reports that confirmed result to Prava and checks its final state.

A browser failure before submission returns the mission to
`PAYMENT_PERMISSION_READY`; retry with a new command ID after fixing the form.
Anything ambiguous after the click becomes `CHECKOUT_OUTCOME_UNKNOWN` and is
never automatically retried. If the merchant result was recorded but Prava
reporting failed, call `report-payment-result`; that endpoint cannot repeat the
merchant checkout.

This bridge is implemented and contract-tested, but the live browser selectors
and full Prava lifecycle remain unobserved on this device. Do not describe the
flow as live end to end until the Phase 1 manual record reaches the final state.

After a confirmed order, Max binds the active Instamart order, polls
`track_order` no faster than every 10 seconds, and calculates departure as
`ETA - MAX_ROBOT_OUTBOUND_SECONDS - MAX_DISPATCH_BUFFER_SECONDS`. The operator
must arm that mission once in the dashboard. A robot HTTP timeout is
outcome-unknown and is never retried automatically.

Set `MAX_ROBOT_OUTBOUND_SECONDS` to the measured p95 outbound time for the
taught route. The API accepts only loopback or private-LAN robot URLs and never
returns the robot PIN, Swiggy coordinates, full address, or rider data.
Run one API worker: the demo delivery loop and dispatch lock are process-local.

## Checks

```bash
uv run pytest -q
uv run alembic check
```

The API binds to loopback by default. Every mission route requires
`Authorization: Bearer $MAX_ADMIN_TOKEN`; mutation commands also require a fresh
mission version and an idempotency key. The operator token must be a non-default
value of at least 24 characters. SQLite/SQLAlchemy is authoritative.
