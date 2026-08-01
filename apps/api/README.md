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

## Checks

```bash
uv run pytest -q
uv run alembic check
```

The API binds to loopback by default. Every mission route requires
`Authorization: Bearer $MAX_ADMIN_TOKEN`; mutation commands also require a fresh
mission version and an idempotency key. The operator token must be a non-default
value of at least 24 characters. SQLite/SQLAlchemy is authoritative.
