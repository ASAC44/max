# Test: Phase 3A local simulated vertical slice

- Date/time and timezone: 1 August 2026, IST
- Operator: Codex
- Goal/question: Does the first Phase 3A implementation preserve authoritative,
  labeled mission truth from text request through a simulated decline and a
  separate staged path?
- Required decision/gate: Local simulated milestone inside Phase 3; not the live
  OpenAI, Swiggy, Prava, notification, or robot gate.
- Environment: local simulation
- Hardware/device/browser/network: project workstation; loopback FastAPI and
  Vite; headless Desktop Chrome visual check
- Service/package/API versions: Python 3.12.13; FastAPI 0.141.1; SQLAlchemy
  2.0.51; Alembic 1.18.5; OpenAI Agents SDK 0.19.1; OpenAI Python 2.52.0;
  React 19.2.8; Vite 7.3.6
- Account/access class: no OpenAI or external-provider credential used
- Primary documentation checked: current OpenAI Agents SDK intro, tracing, Agent
  output, and ModelSettings references

## Preconditions

- The saved code reviewer, consistency auditor, and QA expert reviewed the plan.
- `MAX_AGENT_MODE=simulated` was visible in API and dashboard state.
- A temporary SQLite database and dummy local operator token were used.
- No Prava, Swiggy, notification, or robot service was called.

## Exact steps

1. Resolve the API dependency lock with the Phase 3A runtime and dev extras.
2. Run the backend, agent, workflow, persistence, and API tests.
3. Upgrade a fresh SQLite database with Alembic, run `alembic check`, downgrade
   to base, then upgrade again.
4. Build the Vite dashboard for production.
5. Start FastAPI on loopback against a fresh migrated SQLite database.
6. Create `get 1 milk under ₹300 for work`; inspect the structured intent,
   immutable simulated quote, environment label, and event order.
7. Approve the exact quote with simulated outcome `decline`; inspect separate
   owner approval, Prava-permission, merchant-attempt, merchant-decline,
   result-reporting, and final-Prava-failed events.
8. Stop and restart FastAPI against the same database, then fetch the mission.
9. Start the Vite dashboard and use a headless browser to create, approve and
   decline a mission, create its separate staged branch, record `PACKAGE_READY`,
   run the labeled robot simulation, refresh authoritative state, and capture a
   screenshot.
10. Check dependency audit output and `git diff --check`.

## Expected result

- Deterministic transitions cannot skip approval or dispatch gating.
- Mission snapshot, append-only events, and durable attempts stay correlated.
- Unknown outcomes are non-retryable; interrupted attempts recover as unknown.
- Staged fulfilment cannot rewrite the recorded decline.
- API restart and dashboard refresh recover backend truth.
- Simulated/local labels remain visible.
- No sensitive sentinel appears in persistence.

## Observed result

- `31 passed` in the API/agent/workflow suite, including a bounded SDK-call
  timeout check plus real two-session simultaneous transition, replay,
  root-creation, and staged-child races,
  one-active-mission enforcement, scoped idempotency conflicts, quote expiry,
  provider-result matching, one-child staging, root and staged cancellation,
  and paid-parser replay prevention.
- The identical simultaneous-command replay regression passed 20 consecutive
  isolated stress runs after replay reads were forced to refresh persisted
  mission state.
- Alembic upgrade and downgrade succeeded; `alembic check` reported no new
  operations.
- Vite production build succeeded with 29 transformed modules.
- The live loopback API created a version-2 `AWAITING_OWNER_APPROVAL` mission,
  then a version-5 `PAYMENT_DECLINED` mission with nine ordered events and one
  terminal simulated attempt.
- After a real API process restart, the same mission returned version 5,
  `PAYMENT_DECLINED`, `payment_status=FAILED`, and the same event timeline.
- Headless Chrome completed every dashboard action through staged completion
  and refresh. It rendered `MIXED · STAGED PACKAGE + LOCAL ROBOT SIM`, component
  and provider event metadata, and the final `COMPLETED` state. The operator
  token appeared only as the password-input value, not rendered text or browser
  storage.
- `npm install` reported zero known vulnerabilities and the production build
  completed.
- `git diff --check` produced no whitespace errors.

## Evidence

- Automated tests under `apps/api/tests/`.
- Committed migration `apps/api/migrations/versions/0001_phase3a.py`.
- Dependency locks `apps/api/uv.lock` and `apps/web/package-lock.json`.
- Temporary local runtime IDs were inspected but are not retained as provider
  evidence because all relevant stages were simulated.

## Deviations and interventions

- The sandbox blocked loopback socket binding, so the local runtime/browser
  check used approved loopback execution outside that restriction.
- Starlette's thread-backed test client could not progress in the restricted
  environment. The API check was moved to HTTPX ASGI transport, and API handlers
  use async dependencies/routes while synchronous SQLite work remains short and
  local for the one-active-mission Phase 3A ceiling.
- A live OpenAI Agents SDK call was not run because neither `OPENAI_API_KEY` nor
  an explicit `OPENAI_MODEL` was configured. Offline checks prove the SDK agent
  has no tools and uses `store=False`; they do not prove model behavior.

## Conclusion

- **Observed** for the local simulated Phase 3A core, persistence, API, and
  dashboard build/runtime.
- What this proves: the code enforces and displays the planned local simulated
  workflow, important safe failures, restart persistence, staged separation,
  and the no-tool Agents SDK construction boundary.
- What this does not prove: a live OpenAI extraction, final model suitability,
  Swiggy or Prava behavior, a real notification, a navigation-team bridge, or
  physical robot behavior.
- Follow-up: configure a server-side OpenAI key plus explicit model and run one
  redacted extraction/clarification smoke test; then await Mohit's Phase 1
  evidence before replacing simulated commerce/payment behavior.
- Documents/decisions updated: `README.md`, `DECISIONS.md`, `ARCHITECTURE.md`,
  `ROADMAP.md`, `VALIDATION.md`, and app READMEs.
