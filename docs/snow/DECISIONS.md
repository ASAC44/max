# Decision Ledger

> A decision is valid only when it is explicit here. Candidates and ideas are
> not decisions. Update the evidence and affected documents whenever a decision
> changes.

## Settled product decisions

| Decision | Status | Reason/evidence |
| --- | --- | --- |
| Product name is **Max** | Confirmed | Team decision; public README updated |
| Max is a personal embodied agent, not a public delivery bot | Confirmed | Product direction |
| The intended owner interface includes natural voice | Confirmed | Mic and speaker added to product scope |
| Max combines digital commerce with physical pickup and return | Confirmed | Current product pitch and scope |
| The purchase target is a supported online merchant flow | Confirmed | Prava requires a card-capable merchant checkout |
| Owner approval is required for the exact purchase | Confirmed | Product safety rule and Prava model |
| Prava is the payment-permission layer | Confirmed | Current Prava research in `PRAVA.md` |
| The hackathon can use Prava sandbox credentials and an expected merchant decline | Confirmed | Direct Prava staff judging clarification; preserve original evidence |
| UPI QR, P2P, and paying arbitrary people are outside the current Prava scope | Confirmed | Prava docs, terms, and staff reply |
| Negotiation is excluded from the MVP | Confirmed | Team scope decision |
| Unapproved substitutions are excluded | Confirmed | Team scope and safety decision |
| Shelf navigation and product recognition are excluded | Confirmed | Items are prepared at a pickup point |
| Navigation implementation belongs to the navigation teammate | Confirmed | Team work division |
| Hardware implementation belongs to the hardware teammates | Confirmed | Team work division |
| The navigation team owns the backend-to-robot bridge and contract | Confirmed | User clarification on 1 August 2026; Snow consumes their tested interface but does not design or implement their backend/robot work |
| Main agent, payment integration, voice, notifications, dashboard, and overall software integration belong to the software owner | Confirmed | Team work division |
| OpenAI is the main-agent LLM provider | Confirmed | User decision on 31 July 2026; the exact model still requires deployment-fit testing |
| OpenAI is the first voice provider to validate | Planned | Start with a controlled STT → agent → TTS pipeline; test Realtime next and external voice providers only if evidence shows a gap |
| Hosted SDK/API sandbox is the first Prava validation path | Confirmed | Team decision and current official sandbox guidance; this does not select the final integration until the manual gate passes |
| Prava Browser Harness is available only through MCP/CLI; SDK/API applications must implement their own UCP path | Confirmed | Direct Prava staff follow-up on 31 July 2026; preserve the original message |
| Zepto MCP is excluded from the active hackathon path | Rejected | Auth, tool listing, serviceability, and empty-cart reads worked, but four exact searches returned an opaque `Too Many Requests` error with no result or documented recovery; repeated project attempts made it too unreliable for the remaining schedule. See `TEST-VIRGIN.md` |
| Swiggy Instamart MCP plus normal-browser checkout is the only active commerce candidate | Observed in part | Mohit's 1 August run confirmed OAuth, search, cart, ₹147 quote, exact browser parity, and a new-card option; payment/passkey/decline remain unconfirmed |
| Shopify/UCP and generic shopping are out of the active hackathon plan | Rejected | Product must use Indian quick commerce; no time will be spent building a generic UCP path |
| No merchant-specific Prava wrapper is assumed | Confirmed | Max will combine the observed merchant path with current Prava SDK/API behavior; historical or removed wrappers are evidence only |
| The primary judging transaction claim is a Swiggy browser checkout attempt declined by a Prava sandbox credential | Planned | User's demo decision plus Prava staff guidance; Mohit's Phase 1 run must observe it before it is described as working |
| Mohit's first Swiggy + Prava Phase 1 run is an evidence handoff, not a gate pass | Confirmed | The record stops at hosted `Verification Unavailable`; the user must configure OAuth afresh on their device and the verification/merchant portion must still be run |
| Snow builds the provider-neutral main agent and dashboard while Mohit validates commerce/payment | Confirmed | User schedule decision on 1 August 2026; only the live adapter and final transaction claim wait for Mohit's evidence |
| A staged robot demonstration remains separate from the recorded sandbox decline | Confirmed | The dashboard may start a visibly labeled staged mission but must never overwrite or relabel the Prava/merchant result |
| Linq is the preferred notification path; Telegram is the fallback candidate | Planned | Hackathon track preference; both require manual validation |
| Evidence gates block only the dependent external integration, not independent core/dashboard work | Confirmed | Parallel execution is required by the remaining hackathon schedule |
| Stripe is not Max's agent-payment path | Rejected for this workstream | The unrelated remote Stripe implementation, robot-server endpoints, tests, config, and demo document were removed; Git history retains them if the team ever makes a separate decision |

## Settled Phase 3A implementation decisions

| Decision | Status | Reason/evidence |
| --- | --- | --- |
| Backend is Python with FastAPI | Confirmed | Small synchronous API surface, direct compatibility with the OpenAI Agents SDK and SQLAlchemy, and team decision after the reviewed Phase 3A plan |
| Main-agent runtime is the OpenAI Agents SDK over its default Responses API path | Confirmed | User decision on 1 August 2026 after comparing direct Responses, Agents SDK, and PydanticAI; the SDK is limited to typed request interpretation and clarification |
| SQLite with SQLAlchemy and Alembic is the Phase 3A state store | Confirmed | One local operator, restart-safe audit state, transactional writes, and a committed migration are required now; deployment topology remains open |
| Admin dashboard is React with Vite | Confirmed | One local single-page dashboard using native fetch and CSS is sufficient; no router, global store, component kit, or WebSocket is selected |
| SQLAlchemy mission/event records, not the Agents SDK, own workflow truth | Confirmed | Required by the approved money/motion boundary and the three-agent plan review |
| The live adapter is one hackathon path, not a generic browser framework | Confirmed | Instamart address/search/cart/quote and pre-submit recheck feed a dedicated local Chromium card form; credentials remain memory-only, the click occurs once, unknown outcomes never retry, and confirmed results are reported to Prava. The browser portion is implemented/contract-tested but live-unobserved |

Use the already configured `gpt-5.4-mini` for the first live extraction smoke
to avoid adding another variable. Record the exact model ID; compare a current
GPT-5.6 option only after the full path works.

## Settled execution order

1. Review and approve this handbook.
2. Run two tracks immediately: Mohit validates Swiggy/browser/Prava while Snow
   builds the mission core, OpenAI text-agent path, persistence, simulated
   provider boundaries, and admin dashboard.
3. Snow reviews Mohit's evidence, freezes the observed live adapter contract and
   truthful demo wording, then replaces the simulated boundary.
4. Research, select, and integrate voice.
5. Research, select, and integrate Linq; keep Telegram only as a tested fallback.
6. Consume the navigation team's tested backend/robot interface; do not take
   ownership of their prototype, bridge, or hardware work.
7. Test failure paths and the complete demo end to end.

Do not reverse this order merely because one implementation is easier to start.

## Open architecture decisions

| Decision needed | Candidates known today | Evidence required before choosing |
| --- | --- | --- |
| Prava integration surface | Hosted SDK/API is preferred; MCP/CLI remains a fallback if owning checkout is impractical | Manual flow, credential handling, merchant compatibility, and demo reliability |
| Swiggy commerce contract | Instamart MCP for auth/search/cart/quote plus normal browser for card entry is the candidate | Same-account cart continuity, exact MCP tools/shapes, complete total, browser card form, submission side effect, decline, and order-history result observed by Mohit |
| Main-agent OpenAI model | Not selected | Tool calling, latency, reliability, cost/credits, structured output, actual Raspberry Pi/backend deployment fit |
| Voice architecture | OpenAI STT → agent → TTS baseline, OpenAI Realtime, external fallback only if needed | Noise, latency, interruption, confirmation safety, Pi/network performance, credits |
| Notification provider | Linq preferred, Telegram fallback | Auth/access, send/receive behavior, latency, failure recovery, hackathon eligibility |
| Navigation-team interface consumed by Max | Supplied and owned by the navigation team | Their tested commands, acknowledgements, telemetry, event names, timeout, and emergency-stop behavior |
| Pickup confirmation | Hardware signal, operator confirmation, other tested mechanism | Hardware availability and repeatable evidence |
| Deployment topology | Pi-only, backend service plus Pi client, local network split | Network reliability, compute limits, secrets, recovery, demo venue conditions |

## Candidates that are not decisions

The following have been researched or discussed but must not be described as the
chosen architecture:

- ONDC or Pramaan;
- Prava MCP/CLI as a payment-integration fallback;
- hosted Prava API;
- embedded Prava SDK;
- Linq;
- Telegram; and
- any particular OpenAI model.

Zepto, Shopify/UCP, and generic shopping are rejected decisions, not fallback
candidates.

## Questions that do not block the hackathon MVP

- Whether Indian-issued cards work in Prava production.
- Full production onboarding and KYB.
- Mandates and recurring autonomous purchases.
- Exact production pricing.
- General merchant coverage beyond the selected demonstration.
- Multi-owner or public deployment.

Keep useful research about these topics, but do not delay the current MVP for
them.

## Decision record template

Append a short record when an open decision is closed or changed:

```markdown
### D-YYYYMMDD-short-name

- Status: accepted | superseded | rejected
- Decision:
- Scope affected:
- Evidence:
- Alternatives tested:
- Why this choice:
- Limits/failure conditions:
- Documents/code to update:
```

Do not record “we chose it because it seems easiest” without testing the
assumption that it satisfies the relevant gate.

### D-20260731-handbook-approved

- Status: accepted
- Decision: Approve the Max product/MVP scope and execution order; begin Phase 1.
- Scope affected: Project roadmap and current phase.
- Evidence: Explicit user approval on 31 July 2026.
- Alternatives tested: Not applicable.
- Why this choice: The reviewed handbook matches the intended hackathon scope.
- Limits/failure conditions: Phase 1 implementation remains blocked by its own
  manual evidence gate.
- Documents/code to update: `README.md`, `ROADMAP.md`.

### D-20260731-openai-and-staged-demo

- Status: accepted
- Decision: Use OpenAI as the LLM provider and first voice provider; preserve a
  real sandbox decline, then start any robot continuation as a separate staged
  demo event.
- Scope affected: Model evaluation, voice research, dashboard, and demo story.
- Evidence: User decision plus current provider documentation; runtime behavior
  remains untested.
- Alternatives tested: ElevenLabs and Fish Audio reviewed but not manually
  tested.
- Why this choice: It minimizes providers while retaining a tested-fallback
  path if OpenAI fails the voice gate.
- Limits/failure conditions: Exact OpenAI models and voice architecture remain
  open until their roadmap tests pass; staged state must never be presented as
  a successful payment or merchant order.
- Documents/code to update: `ARCHITECTURE.md`, `ROADMAP.md`, `VALIDATION.md`.

### D-20260801-zepto-mcp

- Status: superseded by `D-20260801-zepto-rejected-and-swiggy-delegated`
- Decision: Use the official Zepto MCP at `https://mcp.zepto.co.in/mcp` as
  Max's only active commerce source. Use Prava SDK/API sandbox for the judging
  decline path if Phase 1 proves the Zepto card-checkout handoff.
- Scope affected: Commerce research, payment validation, architecture, roadmap,
  demo story, and validation matrix.
- Evidence: Zepto's current official repository documents live search, cart,
  card checkout/order placement, order history, Indian phone/OTP OAuth, and a
  production-only environment. Its live endpoint publishes OAuth resource and
  authorization metadata, observed in
  `TEST-2026-08-01-zepto-mcp-preflight.md`. OpenAI's current API documentation supports remote
  MCP in Responses and Realtime. Prava's current Dining page says Zepto can be
  paired with Prava Pay. A historical official Zepto-Prava skill documents the
  intended card-link handoff, but it was removed from the current main branch.
- Alternatives tested: Shopify/UCP rejected by product direction; Swiggy kept
  outside the active plan because Zepto documents card checkout more directly.
- Why this choice: It matches the required Indian quick-commerce experience and
  supplies discovery, cart, payment-method, order, and history boundaries from
  one official source.
- Limits/failure conditions: Zepto MCP has no sandbox. The team's OAuth, final
  quote, exact current tool schema, card-link behavior, Prava sandbox credential
  entry, visible decline, and safe terminal status are not working claims until
  Phase 1 reproduces them. A real Zepto order is forbidden without separate
  explicit production-purchase approval.
- Documents/code to update: `README.md`, `PRODUCT.md`, `PRAVA.md`,
  `ARCHITECTURE.md`, `ROADMAP.md`, and `VALIDATION.md`.

### D-20260801-zepto-rejected-and-swiggy-delegated

- Status: accepted
- Decision: Stop spending hackathon time on Zepto. Use Swiggy Instamart MCP for
  discovery/cart and the matching normal Swiggy browser for card checkout if the
  complete path passes. Delegate the Phase 1 run and evidence collection to
  Mohit; Snow reviews the gate and owns later integration.
- Scope affected: Commerce provider, Phase 1 ownership, payment handoff,
  architecture, roadmap, validation matrix, and demo wording.
- Evidence: `TEST-VIRGIN.md` records authenticated Zepto access, a serviceable
  store, and working empty-cart reads, but four product searches returned only
  an opaque `Too Many Requests` error. The provider exposed no result,
  structured status, retry window, or documented recovery. The user reports
  several prior retries/retirements and explicitly rejected more Zepto work.
  The Swiggy test procedure and evidence form are in `docs/mohit/`.
- Alternatives tested: Zepto was tested and rejected for project reliability;
  Shopify/UCP remains outside the quick-commerce scope. Swiggy is not yet
  accepted as working—it is the next bounded candidate.
- Why this choice: A time-boxed, delegated Swiggy test avoids blocking all other
  team work on an opaque Zepto search failure while preserving a truthful gate.
- Limits/failure conditions: Swiggy MCP checkout is not the card path. The MCP
  and normal browser must expose the same account/cart, the browser must allow a
  fresh unsaved card, the Prava credential must be submitted once, and the
  result must be terminal and redacted. If any condition fails, reduce the demo
  claim or choose a new plan explicitly; do not revive Zepto automatically.
- Documents/code to update: `README.md`, `PRODUCT.md`, `PRAVA.md`,
  `ARCHITECTURE.md`, `ROADMAP.md`, `VALIDATION.md`, and the Zepto test records.

### D-20260801-parallel-software-build

- Status: accepted
- Decision: Begin the main agent and admin dashboard immediately while Mohit
  runs the commerce/payment validation. Build against explicitly simulated
  provider boundaries, then replace only those boundaries with the observed
  Swiggy/Prava contract. Navigation, the robot bridge, and robot-side backend
  work remain owned by the navigation team.
- Scope affected: Current phase, execution order, software ownership, roadmap,
  and integration boundaries.
- Evidence: Explicit user correction on 1 August 2026 that the team cannot wait
  for serial execution and that navigation/backend-robot work is already being
  handled by its owners.
- Alternatives tested: Waiting for the entire Phase 1/2 gate before starting the
  app was rejected as unnecessary schedule blocking.
- Why this choice: Mission state, persistence, agent behavior, dashboard, and
  simulated provider events do not depend on undocumented live payload shapes.
- Limits/failure conditions: Simulated commerce/payment behavior must stay
  visibly labeled and cannot become a working Swiggy/Prava claim. Snow does not
  absorb navigation-team responsibilities.
- Documents/code to update: `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, and
  `VALIDATION.md`.

### D-20260801-phase-3a-stack

- Status: accepted
- Decision: Build Phase 3A with FastAPI, SQLite, SQLAlchemy, Alembic,
  React/Vite, and one OpenAI Agents SDK agent using the default Responses API
  path.
- Scope affected: Local simulated mission core, text-agent path, persistence,
  API, tests, and admin dashboard.
- Evidence: Explicit user selection plus pre-implementation review by the saved
  code reviewer, consistency auditor, and QA expert. The reviewers approved the
  revised plan after deterministic authority, atomic transitions, concurrency,
  trace privacy, and staged-truth requirements were made explicit.
- Alternatives tested: Direct Responses API and PydanticAI were reviewed;
  LangGraph was rejected as unnecessary for this bounded local workflow.
- Why this choice: It supplies typed model output and a maintained agent runtime
  without giving the model authority over persisted mission, money, or motion.
- Limits/failure conditions: The SDK has no payment, checkout, cancellation,
  staged-fulfilment, or robot-dispatch tools. SQLAlchemy owns workflow truth.
  Sensitive trace payloads and provider-side response storage are disabled.
  The exact model and every live external contract remain open.
- Documents/code to update: `ARCHITECTURE.md`, `ROADMAP.md`, `VALIDATION.md`,
  `apps/api/`, and `apps/web/`.
