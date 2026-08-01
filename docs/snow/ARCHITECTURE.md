# System Architecture

> Status: logical architecture approved. Swiggy discovery/cart/quote shapes,
> browser continuity, and Prava session creation are observed once. Hosted
> verification and credential readiness remain unobserved; the one-shot browser
> checkout/report bridge is implemented and contract-tested, not live-proven.

## Architecture goal

Build one observable mission workflow that connects owner intent, commerce,
Prava approval, merchant outcome, robot motion, pickup, return, and notification
without allowing an LLM or external provider to invent state.

## Core principles

1. **One authoritative mission record.** Chat history, robot telemetry, Prava,
   merchant state, and notifications are inputs; none alone is the full truth.
2. **LLM for interpretation and bounded decisions.** Deterministic code owns
   state transitions, validation, money limits, dispatch, timeout, and retry.
3. **External adapters have narrow contracts.** Commerce, Prava, voice, robot,
   and notification providers can be replaced without rewriting mission policy.
   Do not add abstractions until the first verified implementation defines the
   real contract.
4. **Irreversible actions require gates.** Payment, merchant checkout, robot
   dispatch, cancellation, and emergency behavior have explicit prerequisites.
5. **Every external action is correlated.** Use one mission ID and preserve
   provider request/session/order IDs.
6. **Unknown outcomes are first-class states.** Never convert a timeout into
   success or retry an irreversible action blindly.
7. **Manual help is visible.** Human intervention is an event recorded in the
   mission, not hidden during the demo.
8. **The dashboard observes the backend.** It does not maintain a separate
   version of mission truth in browser state.

## Logical component map

```text
                         ┌─────────────────────┐
                         │  Owner interface    │
                         │ voice / test input  │
                         └──────────┬──────────┘
                                    │ request / clarification
                                    ▼
┌─────────────────┐       ┌─────────────────────┐       ┌──────────────────┐
│ Admin dashboard │◀─────▶│ Mission orchestrator│──────▶│Swiggy commerce path│
└─────────────────┘ state └──────────┬──────────┘ tools └──────────────────┘
                                     │
                          ┌──────────┼──────────┐
                          │          │          │
                          ▼          ▼          ▼
                 ┌─────────────┐ ┌─────────┐ ┌────────────────────┐
                 │Prava adapter│ │ State   │ │Notification adapter│
                 └─────────────┘ │ store   │ └────────────────────┘
                                 └────┬────┘
                                      │ commands / events
                                      ▼
                          ┌─────────────────────────┐
                          │ Robot/navigation bridge │
                          └────────────┬────────────┘
                                       ▼
                          hardware + navigation stack
```

This is a responsibility map, not a framework choice.

## Practical hackathon flow

```text
voice/text
→ OpenAI turns the request into validated constraints
→ Swiggy MCP OAuth + live Instamart search/cart/final total
→ identical cart is verified in the normal Swiggy browser
→ owner confirms the exact Swiggy cart
→ Prava SDK/API sandbox session + passkey
→ controlled browser handoff uses the scoped credential once
→ expected Swiggy decline is inspected and reported DECLINED to Prava
→ digital payment flow ends truthfully

separate staged branch
dashboard selects RUN_STAGED_FULFILMENT
→ new branch records SIMULATED_ORDER_CONFIRMED (never edits payment truth)
→ point of contact sends PACKAGE_READY
→ robot travels to fixed handoff point
→ package secured
→ robot returns
```

No dashboard tweak may convert the decline into a Swiggy success. It may create a
new, visibly staged physical mission linked to the same presentation only as a
separate event stream.

## Component responsibilities

### Owner interface

- Captures the request.
- Presents focused clarification questions.
- Presents the exact purchase plan and Prava approval surface.
- Communicates final status and required help.
- Starts as a text harness for core development; voice replaces or wraps it only
  after voice validation.

It must not store the authoritative mission or payment state.

### Mission orchestrator

- Creates the mission ID and structured request.
- Calls the LLM only for bounded interpretation, clarification, comparison, and
  explanation tasks.
- Validates all LLM outputs against schemas and allowed values.
- Calls commerce, Prava, robot, and notification tools only when prerequisites
  are satisfied.
- Applies transition, timeout, cancellation, and recovery policy.
- Records every state change and provider identifier.

The orchestrator is not “an LLM loop that can call everything.” It is a workflow
whose individual states may ask an LLM for a constrained result.

For Phase 3A, the backend is FastAPI and the text interpreter is one OpenAI
Agents SDK agent on its default Responses API path. The SDK receives no tools
that approve money, use credentials, report merchant success, cancel missions,
start staged fulfilment, or dispatch motion. Its typed output is only a proposal
that deterministic application code validates before an atomic SQLAlchemy
transition. SDK sessions are not mission storage. Sensitive trace payloads and
provider-side response storage are disabled.

### Swiggy commerce boundary

The active candidate has two deliberately separate surfaces: the official
Swiggy Instamart MCP for account-scoped commerce and the normal Swiggy browser
for card checkout. Phase 1 must prove they share the same account and cart. Its
logical duties are:

- search products;
- obtain product/variant details and availability;
- create or update a cart;
- produce a final quote with currency, tax, fees, and fulfilment;
- expose the same cart in the normal browser;
- expose a fresh unsaved-card form in that browser; and
- query order status through the browser and read-only MCP tools where safe.

The implemented adapter connects through `npx mcp-remote` and allows only the
observed production Instamart sequence: `get_addresses`, an empty `get_cart`
check, `search_products`, `update_cart`, and final `get_cart`. OAuth is local to
the API machine and completed in the operator's browser. It refuses to clear a
pre-existing cart. Raw address/cart data never leaves the adapter; the mission
receives only the address label, selected product/spin ID, quantity, price/fees,
and total. The MCP checkout path is not used for the card-payment demo.

Do not write a custom Swiggy REST integration or generic browser framework. The
implemented browser bridge attaches to one dedicated operator-controlled
Chromium profile, requires the exact approved total and a visible save-card
control, disables saving, submits once, and classifies only explicit decline or
order-confirmation text. It is contract-tested but remains provisional until a
live run confirms the current Swiggy DOM.

### Prava and checkout boundary

The hosted sandbox and checkout adapter currently:

- creates a session after exact-quote approval with `full_checkout` and an
  optional HTTPS callback URL;
- returns the hosted approval URL and non-secret session/order references;
- polls `payment-result` and persists only state, transaction reference, and a
  credential-presence boolean;
- fetches the credential only immediately before the deterministic browser
  bridge, then drops the local reference;
- rechecks the MCP cart and browser total before submission;
- records a known merchant result before reporting it to Prava; and
- verifies Prava reaches `failed` or `completed`.

Before the submit click, browser failures clear entered fields and return the
mission to payment-ready for an explicit retry. After the click, any ambiguous
result becomes non-retryable outcome-unknown. A failed Prava report can be
retried separately without re-running checkout. The credential never enters
the OpenAI conversation, MCP arguments, dashboard, persistence, logs, traces,
or screenshots.

If MCP or CLI is selected, redefine this boundary from observed behavior. Do not
pretend all three Prava surfaces expose the same checkout or credential model.

### State store

Must persist enough information to recover and audit the demo:

- mission and owner identifiers;
- normalized request and clarification history;
- selected product and quote snapshot;
- owner approval request and result;
- Prava session and transaction references, without sensitive credentials;
- merchant cart, checkout, and order references;
- robot command, acknowledgement, telemetry summary, and pickup result;
- notification attempts and outcomes;
- timestamps, errors, timeouts, cancellations, and manual interventions.

Do not store card numbers, CVV/cryptograms, API secrets, OTPs, passkeys, or full
unnecessary personal data.

Phase 3A uses SQLite through SQLAlchemy with Alembic migrations. One transaction
must validate the current mission/version, update the snapshot, append its
event, and advance the version. Named commands carry globally unique
idempotency keys bound to command scope, target mission, and a semantic request
hash; reusing a key for different input fails closed. The API
offers no generic status mutation. An irreversible provider call first records
an `IN_PROGRESS` attempt, then records its terminal result. An interrupted or
timed-out attempt becomes outcome-unknown and is not automatically retried.
A unique active slot enforces one active errand across root and staged missions;
decline, cancellation, or completion releases it, while outcome-unknown keeps
it locked for explicit inspection.

### Admin dashboard

The dashboard exists for visibility and safe control, not as a second agent.

Minimum views/actions:

- active mission and current blocking state;
- original request and normalized constraints;
- selected merchant/product and exact quote;
- approval and Prava state;
- merchant checkout/order state;
- robot route state and last telemetry time;
- notification status;
- chronological event log;
- explicit cancel, retry-safe operation, and request-help controls where the
  backend permits them; and
- a `Run staged fulfilment` action that creates a new staged branch rather than
  editing the sandbox payment/order outcome; and
- clear distinction between sandbox, simulated, staged, and real events.

The dashboard must not expose scoped payment credentials or raw secrets.

Phase 3A implements this as one React/Vite page using native fetch and CSS. The
API binds to loopback by default, permits only the configured web origin, and
requires the server-side operator token for commands. Every command includes an
expected mission version so stale tabs receive a conflict instead of replacing
newer truth.

### Robot/navigation bridge

The navigation team owns this bridge, its robot-side backend, and its contract.
Max's software consumes the interface they deliver and does not implement their
side. The supplied contract must eventually answer:

- How is a destination identified?
- How is a mission command acknowledged?
- Which states are reported: ready, moving, arrived, blocked, lost, returning,
  docked, emergency stopped?
- How is pickup/cargo confirmation represented?
- What is the heartbeat/telemetry timeout?
- Who may cancel or emergency-stop motion?
- What happens after network loss or process restart?

For the hackathon staged path, dispatch additionally requires a point-of-contact
`PACKAGE_READY` event recorded by the backend. That event may come from the
dashboard or the selected notification channel after it is tested. It is not a
Swiggy order or rider event.

Do not duplicate or replace the navigation team's bridge. Integrate only its
versioned, demonstrated interface.

### Notification adapter

- Sends normalized mission events through Linq or the selected fallback.
- Returns provider message ID and delivery/error status.
- Deduplicates retried events.
- Accepts owner replies only if the selected product flow needs remote input and
  the provider's inbound behavior has been verified.

Notification failure must not corrupt mission state. The dashboard remains the
fallback observation surface.

## Domain records

These are logical records, not final database tables.

### Request

- owner request text/transcript;
- item and quantity;
- product constraints;
- budget value and meaning: exact, maximum, minimum, or range;
- destination/pickup constraint;
- unresolved questions; and
- request revision.

### Quote

- merchant and environment;
- product/variant identifiers and names;
- quantity;
- item subtotal, taxes, fees, shipping, and exact total;
- currency;
- fulfilment/pickup details;
- expiry or freshness timestamp; and
- source response reference.

### Approval

- immutable quote reference/hash;
- exact approved merchant, amount, currency, and items;
- Prava session reference;
- approval URL status;
- approved, rejected, expired, or revoked result; and
- timestamps.

### Merchant checkout

- cart and checkout identifiers;
- submitted quote/approval reference;
- attempt count and idempotency key if supported;
- success, decline, unknown, or error result;
- order ID only when returned by the merchant; and
- raw evidence location with secrets redacted.

### Robot mission

- fixed destination identifier;
- dispatch prerequisite result;
- command and acknowledgement IDs;
- navigation state and last heartbeat;
- arrival, cargo, return, and completion evidence; and
- failure/help reason.

## State model

Do not compress commerce, payment, and robot state into a single ambiguous
`status`. Store their provider states separately and derive the mission phase.

Recommended mission phases:

```text
DRAFT
→ NEEDS_CLARIFICATION
→ READY_TO_SEARCH
→ SEARCHING
→ QUOTED
→ AWAITING_OWNER_APPROVAL
→ PAYMENT_PERMISSION_READY
→ MERCHANT_CHECKOUT_IN_PROGRESS
→ ORDER_CONFIRMED
→ READY_TO_DISPATCH
→ EN_ROUTE_TO_PICKUP
→ AT_PICKUP
→ ITEM_SECURED
→ RETURNING
→ COMPLETED
```

Terminal or intervention phases:

```text
CANCELLED
PAYMENT_DECLINED
CHECKOUT_OUTCOME_UNKNOWN
ORDER_FAILED
ROBOT_BLOCKED
PICKUP_FAILED
HELP_REQUIRED
FAILED
```

Not every flow visits every phase. For the hackathon sandbox decline, the
payment demonstration normally ends at `PAYMENT_DECLINED`. A separately staged
robot demonstration must start through an explicit demo-only dispatch action and
must be labeled as such; it cannot masquerade as fulfilment of a confirmed
merchant order.

The staged branch records `SIMULATED_ORDER_CONFIRMED` and `PACKAGE_READY` as
staged events before reusing the physical mission phases. Neither event changes
the Swiggy checkout state or the Prava session state.

## Normal workflow gates

| Action | Required evidence before action |
| --- | --- |
| Search Swiggy Instamart | Structured request contains required constraints and Swiggy OAuth is active |
| Request approval | Fresh exact quote and supported checkout path exist |
| Obtain/use credential | Owner completed the tested Prava approval flow |
| Submit Swiggy browser checkout | MCP and browser carts, amount, currency, address, Prava approval, and known order side effect all match |
| Retry checkout | Previous attempt is proven not to have charged/ordered, or provider idempotency guarantees it |
| Dispatch product mission | Merchant order and pickup are confirmed |
| Dispatch staged demo mission | Operator explicitly selects labeled demo mode and point of contact confirms the staged package |
| Mark item secured | Pickup mechanism/operator produces the agreed evidence |
| Mark completed | Robot returned and cargo/result is confirmed |

## Failure and recovery policy

- **Ambiguous request:** ask; do not guess.
- **No valid product:** explain constraint failure; allow owner revision.
- **Quote changed:** invalidate approval and request a new one.
- **Approval rejected/expired:** cancel or restart with a fresh reviewed quote.
- **Prava timeout:** inspect session; never infer approval.
- **Merchant decline:** report `DECLINED` to Prava and stop digital fulfilment.
- **Merchant outcome unknown:** query merchant/Prava; do not retry blindly.
- **Robot not acknowledging:** do not assume movement; alert operator.
- **Robot heartbeat lost:** enter help/emergency policy agreed with navigation.
- **Pickup absent:** wait only for a bounded tested time, then request help or
  follow the agreed return policy.
- **Notification failure:** record it, retry safely, and keep dashboard state
  available.
- **Provider outage:** show the exact dependency failure and use a tested backup
  only if its activation conditions are documented.

## Security boundaries

- Provider secrets stay server-side or in a dedicated secret store.
- Swiggy OAuth access/refresh tokens stay server-side, are never placed in model
  instructions or logs, and are supplied to a remote-MCP call only as required
  by the tested OpenAI/MCP client contract.
- Frontend receives only values designed for public/hosted use.
- Scoped payment credentials live only for the checkout operation and are never
  persisted or logged.
- Dashboard and robot commands require authentication appropriate to the demo
  network; “it is only a hackathon” is not authorization.
- Owner approval is bound to an immutable quote.
- External callbacks and messages are validated and correlated.
- Tool inputs are schema-validated; merchant text is untrusted data, not agent
  instruction.
- Logs are structured and redacted.
- Emergency stop and payment cancellation remain deterministic controls.

## Observability

Every event should contain:

- mission ID;
- component/provider;
- event type;
- local state before and after;
- provider request/session/order ID where relevant;
- timestamp;
- environment: local, sandbox, staged demo, or production;
- success/error class; and
- whether a human intervened.

Measure at least request-to-quote, approval wait, merchant checkout, robot
dispatch-to-arrival, pickup wait, return, and notification latency during the
final rehearsals.

## Choices intentionally deferred

Do not select these inside this architecture document without completing the
matching roadmap experiment:

- programming language/framework;
- exact OpenAI model;
- hosting/deployment topology;
- Prava SDK/API versus MCP/CLI;
- final OpenAI voice architecture or evidenced external fallback;
- Linq versus Telegram behavior;
- robot transport protocol; and
- pickup sensor/confirmation method.

The architecture becomes implementation-ready one boundary at a time, after the
provider or teammate contract is observed and recorded.
