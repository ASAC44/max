# Execution Roadmap

> Work moves through evidence gates. Finishing code is not an exit condition
> unless the required behavior has been observed in the intended environment.

## Phase 0 — Approve the plan

**Status: passed on 31 July 2026 by explicit user approval.**

### Entry

- Product direction has changed enough that previous implementation assumptions
  are unsafe.

### Work

- Review `PRODUCT.md`, `DECISIONS.md`, `ARCHITECTURE.md`, and this roadmap with
  the team.
- Correct scope, ownership, terminology, and the truthful demo claim.
- Confirm the navigation and hardware owners understand the proposed software
  boundary.
- Mark disagreements and unknowns instead of silently choosing.

### Evidence

- Team-reviewed handbook.
- Explicit list of open decisions.
- No contradiction between public README and private scope.

### Exit gate

- The user approves the product/MVP scope and execution order.

No implementation beyond disposable experiments begins before this gate.

## Phase 1 — Manually validate Swiggy Instamart and Prava

**Status: verified through merchant confirmation on 1 August 2026; blocked by
the selected Instamart store closing before the terminal merchant result, so the
exit gate has not passed.**

Mohit's first run stopped at hosted verification. Snow's fresh-device run then
confirmed live OpenAI interpretation, Swiggy OAuth/search/cart/₹110 quote,
Prava card setup plus OTP/passkey, `awaiting_result`, credential readiness, and
browser card entry through Swiggy's final save-or-pay confirmation. The card was
not saved. Swiggy rejected the Work address, MCP returned cart warning 135,
order history stayed empty, and Prava remained `awaiting_result`; the UI then
showed the store closed until 06:00. Do not call this a card decline. Repeat only
with a fresh mission after the store opens.

### Entry

- Phase 0 passed.
- Current `PRAVA.md` has been read completely.
- Sandbox credentials are available without exposing them in the repository.

### Goal

Replace theoretical payment and shopping knowledge with one reproducible Swiggy
Instamart MCP → matching browser cart → Prava sandbox-decline path that the main
agent can later call.

### Ownership

- **Mohit:** run the complete test, protect secrets, and fill in
  `docs/mohit/DOCUMENTATION_TEMPLATE.md` using
  `docs/mohit/DIRECTIONS.md`.
- **Snow:** answer genuinely blocking product questions, review the returned
  evidence, accept/reject the gate, and own the resulting implementation.
- Sharing sandbox access does not transfer authority to use a real card, create
  a successful production order, or weaken any stop condition.

### Work

1. Recheck the current official Swiggy Instamart MCP and Prava SDK/API docs and
   record exact versions.
2. Connect an MCP-capable client, complete Swiggy OAuth/mobile OTP outside model
   context, and record the live tool names and redacted response shapes.
3. With one cheap non-restricted item and a serviceable saved address, reproduce
   search, exact variant, availability, cart mutation, full INR total, fees,
   delivery, and ETA.
4. In a normal browser logged into the same Swiggy account, prove the identical
   cart and total appear and that checkout exposes a fresh unsaved-card form.
   Never call the MCP `checkout` tool for this test.
5. Create one hosted Prava SDK/API sandbox session bound to Swiggy, the exact
   cart description, fresh total, INR, and verified merchant URL.
6. Complete sandbox card setup, OTP where required, and passkey approval. Record
   exact Prava states and keep scoped credentials out of logs and model context.
7. Immediately recheck merchant, address label, items, quantities, currency,
   total, and card form; abandon the session if anything changed.
8. Submit the scoped credential exactly once in the normal browser with save-card
   disabled. Record the visible merchant result and inspect browser order history
   plus safe MCP status tools before classifying it.
9. Only after a confirmed decline, report `DECLINED` to Prava and verify final
   `failed`. Never retry an unknown result.
10. Return the completed template and redacted evidence to Snow for gate review.

The two files under `docs/mohit/` are the canonical detailed procedure and
evidence structure. `PRAVA.md` supplies the payment rules and research context.

### Required evidence

- Redacted request/response or screen evidence for every Prava lifecycle state.
- Reproducible commands or steps with exact environment and package versions.
- Merchant checkout evidence showing what was truly attempted and returned.
- A Swiggy capability table covering OAuth, search, variant, MCP cart, browser
  cart parity, full quote, new-card form, checkout side effect, and terminal
  status.
- Final Prava surface and Swiggy/browser contract, recorded in `DECISIONS.md`.
- Known failure behavior and the exact demo claim supported by the test.
- Swiggy MCP client/version, OAuth callback class, allowed tool names, redacted
  address/product/cart/order IDs, totals, browser behavior, and status.

### Exit gate

All must be true:

- A payment session, owner approval, credential readiness, merchant attempt,
  result report, and final Prava state have been observed.
- The chosen integration surface is accessible to the team.
- The combined Swiggy MCP/browser path exposes every commerce capability the
  planned agent needs, or the
  scope/demo claim is explicitly reduced to what it really exposes.
- Secrets and scoped credentials are absent from logs and commits.
- The truthful hackathon transaction story is written and accepted.

If this gate fails, record the exact failure and choose explicitly between a
reduced demo claim and a new merchant plan. Do not fall back to Zepto or build
against an imagined interface.

### Concurrent Snow schedule while Phase 1 finishes

Snow does not wait and does not take navigation-team work. Current result:

1. **Done:** stack, mission persistence, chronological events, deterministic
   transitions, typed text agent, and dashboard.
2. **Done locally:** labeled simulated decline and separate staged branch.
3. **Done in code, live run pending:** observed Swiggy MCP quote subset, fresh
   cart recheck, hosted Prava create/poll, one-shot dedicated-browser checkout,
   and confirmed-result reporting. Credentials stay out of persisted state.
4. **Now:** fix the usability/flow problems observed during the live run; do not
   wait for the store or take navigation-team work.
5. **After 06:00:** create a fresh quote and payment session, live-test automatic
   `Just pay`, record the merchant result, report it, and verify Prava's final
   state. Those four terminal behaviors remain unobserved and keep Phase 1 open.

Navigation, hardware, and the backend-to-robot implementation remain owned by
their teammates. Snow later consumes the interface they provide.

## Phase 2 — Freeze the executable software contract

### Entry

- Phase 0 passed.
- Provider-neutral schemas may be frozen now; provider-specific fields remain
  provisional until Phase 1 passes.

### Goal

Define the smallest internal contract needed to build now, then add observed
provider fields without redesigning the application.

### Work

- Update `ARCHITECTURE.md` with the observed Prava, Swiggy MCP, and browser
  handoff calls.
- Agree on request, quote, approval, checkout, and error schemas.
- Accept the navigation team's backend/robot contract when they deliver it; do
  not design or implement their side.
- Define the minimum dashboard state and recovery controls.
- Choose runtime, model, persistence, and deployment only from actual needs.
- Write one contract check for each irreversible boundary.
- Produce a thin vertical-path implementation plan; avoid speculative plugin
  systems or multiple unused providers.

### Evidence

- Versioned interface examples using redacted real test shapes.
- Accepted decision records for the chosen stack.
- Navigation interface example supplied and demonstrated by its owning team;
  Snow's app can consume it without implementing their side.

### Exit gate

- Every component can name its input, output, timeout, error, and source of truth.
- No architecture box depends on an untested external capability.

## Phase 3 — Build the main agent and admin dashboard

**Status: active in parallel with Phase 1.**

### Phase 3A — Local simulated vertical slice

**Status: local core observed; manual review and live-provider smoke pending.**
The simulated core/API/dashboard and restart behavior passed on 1 August 2026;
39 focused tests now pass, including the bounded Swiggy/Prava adapter contract.
The live OpenAI, local Swiggy OAuth, and Prava API runs still require credentials
and operator interaction. Merchant checkout is implemented but remains live-unobserved.

The selected stack is FastAPI, SQLite, SQLAlchemy, Alembic, React/Vite, and one
OpenAI Agents SDK text agent. The first executable path must preserve separate
commerce, Prava, merchant-checkout, notification, and robot states while using
clearly labeled local simulations. SQLAlchemy remains authoritative; the agent
only extracts a typed request and asks focused clarification.

Phase 3A exits only after the same persisted mission survives refresh and
backend restart; exact approval cannot be bypassed; duplicate or stale commands
cannot duplicate events; timeout becomes outcome-unknown without blind retry;
the recorded decline remains unchanged by a separate staged branch; dispatch
waits for `PACKAGE_READY`; and the labeled notification/robot simulation reaches
return/completion. The test gate also covers budget meaning, invalid model
output, instruction-like merchant text, quote invalidation, cancellation,
forbidden dispatch, secret leakage, and a redacted live Agents SDK smoke test.

### Entry

- Phase 0 passed.
- The internal mission and event boundaries in `ARCHITECTURE.md` are sufficient
  to start; unverified external events must be simulated and labeled.

### Goal

Run the complete digital workflow through deterministic mission state using a
text input harness, an OpenAI agent, and a real admin dashboard. Use labeled
simulators for external paths until their live contracts pass.

### Work

1. Implement mission persistence and event logging.
2. Implement request parsing and schema validation.
3. Implement focused clarification.
4. Implement simulated commerce/payment boundaries now; replace them with only
   the observed Swiggy MCP/browser and Prava subsets after Mohit's handoff.
5. Keep payment credentials outside persistence, logs, dashboard, and model
   context in both simulated and live modes.
6. Implement approval, quote-change invalidation, decline, timeout, cancellation,
   unknown-outcome, and retry rules.
7. Implement the minimum admin dashboard against the same backend state.
8. Consume a labeled robot-event simulator until the navigation team supplies
   its interface. Do not implement their bridge or robot backend.
9. Add one runnable check per non-trivial workflow boundary.

### Required evidence

- One mission ID links request, quote, approval, Prava, merchant, and simulated
  robot events.
- Dashboard accurately renders persisted state after refresh/restart.
- LLM output cannot skip approval, widen amount, invent merchant success, or
  dispatch the robot outside the gate.
- Important failure cases end in explicit safe states.

### Exit gate

- Parallel build milestone: the simulated text-driven workflow and dashboard run
  repeatedly with correct persisted state and failure handling.
- Live integration milestone: the simulated commerce/payment boundary is
  replaced only after Phase 1 evidence freezes its contract.
- The text-driven digital flow runs repeatedly from request through its truthful
  merchant result and produces a correct dashboard/event trail.
- No manual database editing or hidden state changes are required.

## Phase 4 — Research and integrate voice

### Entry

- The text-driven request/clarification/approval behavior is stable.

### Goal

Replace the development input harness with a reliable voice experience without
weakening purchase confirmation.

### Research questions

- Realtime speech-to-speech or STT → agent → TTS?
- Where does audio processing run: Pi, backend, or split?
- Actual latency on the demo network and Raspberry Pi hardware?
- Performance with canteen/campus noise, accents, interruption, and silence?
- How are wake, turn end, barge-in, cancel, and replay handled?
- Which transcript is stored, redacted, and shown in the dashboard?
- How does the owner verify merchant, item, and total before Prava approval?
- What happens when confidence is low or the network drops?

### Work

- Start with an OpenAI STT → agent → TTS pipeline so transcripts and
  purchase checks remain explicit.
- Test OpenAI Realtime only after the controlled pipeline has a baseline.
- Test ElevenLabs or Fish Audio only if OpenAI fails a measured requirement;
  do not add a second voice provider for preference alone.
- Test a fixed phrase set plus natural variations in the real environment.
- Preserve text request schemas so voice cannot bypass validation.
- Make critical purchase details visible/audible and require the existing Prava
  hard approval.
- Test interruption, correction, cancellation, and false activation.

### Exit gate

- The owner can create and correct the same structured requests as the text
  harness in the real demo environment.
- Voice failure falls back safely without creating or dispatching a purchase.

## Phase 5 — Research and integrate notifications

### Entry

- Mission event meanings are stable.

### Goal

Deliver useful progress and help requests through Linq, with a fallback selected
only from evidence.

### Work

1. Read current Linq docs, hackathon requirements, authentication, limits, and
   supported send/receive behavior.
2. Test account access and a minimal message.
3. Test each required event, duplicate handling, failure, retry, and latency.
4. Test inbound owner replies only if the product flow needs them.
5. If Linq cannot meet the gate, repeat the same tests with Telegram and record
   the fallback decision.
6. Keep provider payloads outside mission policy through the notification
   adapter.

### Exit gate

- The selected provider reliably delivers every required event in the demo
  environment.
- Provider failure is visible and does not alter authoritative mission state.
- Linq versus Telegram status is recorded honestly in the README/demo material.

## Phase 6 — Integrate navigation and hardware boundary

**Status: parallel prototype exists; phase gate has not passed.** The repository
contains the hardware-free implementation described in
`docs/AI_NAVIGATION_PLAN.md`. A minimal local run passed 13 core tests, while 2
NumPy-dependent modules could not import and 3 socket tests were unavailable;
see `TEST-2026-08-01-navigation-core.md`. No ROS/Gazebo or physical-route claim
has been observed in this handbook.

**Owner: navigation/hardware team.** They own the prototype, robot-side backend,
bridge, simulation, and physical validation. Snow's responsibility is limited
to consuming their delivered events/commands in Max's main software during final
integration.

### Entry

- Navigation teammate supplies the agreed command/event interface.
- The target route and pickup point are physically tested by that team.
- Phase 3 workflow can drive the simulator correctly.

### Goal

Replace simulated robot events with real, observable robot events without
changing commerce/payment policy.

### Work

- Connect authenticated mission command and acknowledgement.
- Display navigation state and heartbeat in the dashboard.
- Integrate arrival, pickup/cargo, return, blocked, lost, cancel, and emergency
  events supported by the real stack.
- Test network interruption, stale telemetry, restart, and operator-help flows.
- Confirm exactly what counts as autonomous versus manually assisted.

### Evidence

- Correlated backend and robot event logs.
- Physical route recordings and timing.
- Demonstrated stop/recovery behavior.
- No hidden teleoperation described as autonomy.

### Exit gate

- The backend can safely command and observe one complete pickup-and-return
  mission and at least the critical blocked/cancel path.

## Phase 7 — End-to-end integration and rehearsal

### Entry

- Payment/merchant, agent/dashboard, navigation/hardware, voice, and notification
  gates have individually passed.

### Goal

Prove the exact hackathon story as one correlated system under realistic
conditions.

### Work

- Freeze the truthful demo script and environment labels.
- Run from voice request through the final digital result and physical mission.
- After the expected Swiggy/Prava decline, require an explicit staged-mode action
  and point-of-contact `PACKAGE_READY` event before the physical mission.
- Verify every dashboard and notification transition.
- Test at the real venue or a close network/noise/layout equivalent.
- Inject likely failures: ambiguous request, no item, changed quote, declined
  payment, Prava timeout, merchant unknown outcome, robot blocked, pickup absent,
  notification outage, and process restart.
- Measure timing and set bounded timeouts.
- Prepare a tested fallback for only the failures that cannot be fixed before the
  demo.
- Remove or visibly label all simulators, staged packages, and sandbox results.

### Final evidence

- Repeatable end-to-end run with one mission ID.
- Redacted event timeline.
- Exact demo claims mapped to observed evidence.
- Critical failure/recovery results.
- Setup and run instructions reproduced by a teammate.
- Public README and architecture docs updated to match the demonstrated build.

### Exit gate

- The complete system works repeatedly without hidden state editing.
- Every non-real component or event is disclosed.
- A teammate can run the demo using the documented procedure.
- The software owner's responsibilities listed in `PRODUCT.md` are complete.

## Stop conditions

Stop the current phase and investigate when:

- a primary source contradicts the chosen behavior;
- the observed API differs from its schema;
- an external action has an unknown outcome;
- a secret or payment credential appears in logs;
- the team cannot explain whether an event is real, sandboxed, staged, simulated,
  or mocked;
- a provider cannot satisfy a required capability;
- dashboard and backend state disagree; or
- manual intervention is required but not represented in the event trail.
