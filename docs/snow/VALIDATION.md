# Validation and Evidence Standard

> Max is considered working only where evidence says it is working. A document,
> successful API call, isolated mock, or polished UI cannot prove the complete
> system.

## Evidence ladder

From weakest to strongest:

1. Memory or assumption.
2. Search result or third-party summary.
3. Vendor marketing, social post, or demo video.
4. Current official documentation or schema.
5. Isolated manual test in a different environment.
6. Repeatable test in the intended environment.
7. Integrated test with real component boundaries.
8. Repeatable end-to-end run under demo conditions.

Architecture choices require at least level 4 and normally level 6. Claims that
Max works end to end require level 8.

Official documentation can confirm a supported contract. It cannot confirm that
our credentials, account, network, code, hardware, or merchant setup works.

## Environment labels

Every result must state one:

- **local:** code runs locally against local fakes or simulators;
- **sandbox:** vendor-provided test system, no production money/order assumed;
- **staged demo:** a physical item/person/event is arranged for demonstration;
- **production:** real external service and consequences; or
- **mixed:** identify the environment of every stage separately.

Never use “real” as a general label for a mixed flow.

## Experiment record template

Create a new record only when an experiment is actually run. Use a clear dated
filename under `docs/snow/`, for example `TEST-2026-08-01-prava-hosted.md`.

```markdown
# Test: short name

- Date/time and timezone:
- Operator:
- Goal/question:
- Required decision/gate:
- Environment:
- Hardware/device/browser/network:
- Service/package/API versions:
- Account/access class (never include secrets):
- Primary documentation checked:

## Preconditions

- ...

## Exact steps

1. ...

## Expected result

- ...

## Observed result

- ...

## Evidence

- Redacted request/response IDs, screenshots, logs, video, or provider state.

## Deviations and interventions

- ...

## Conclusion

- Confirmed | Observed | Rejected | Inconclusive
- What this proves:
- What this does not prove:
- Follow-up:
- Documents/decisions updated:
```

## Experiment rules

- Test one important unknown at a time.
- Write the expected result before running the test.
- Record exact versions and environment.
- Preserve provider request IDs but redact sensitive values.
- Do not silently repeat a failed payment or checkout.
- Distinguish setup error, unsupported feature, permission issue, provider error,
  and product defect.
- Reproduce important success at least twice before building on it.
- Have a teammate reproduce critical setup/run instructions before the final
  demo.
- A simulator is valid for testing our side of a contract, but it does not prove
  the external component.
- Passing the happy path does not satisfy a gate whose failure behavior remains
  unknown.

## Capability validation matrix

Update the status and evidence link as work progresses.

| Capability | Current status | Required proof |
| --- | --- | --- |
| Voice captures owner request | Planned; OpenAI baseline selected | OpenAI chained pipeline passes actual mic/audio tests in demo noise; test Realtime next and an external provider only if a measured gap remains |
| Agent extracts constraints | Observed with the local simulated parser; Agents SDK construction checked offline, live call pending | Structured output tests for item, quantity, budget meaning, destination plus a redacted live Agents SDK smoke |
| Agent asks clarification | Observed in local workflow tests; live Agents SDK pending | Missing/ambiguous required fields stop progress and produce focused question |
| Zepto commerce path | Rejected for this hackathon | `TEST-VIRGIN.md` preserves successful auth/tool/serviceability/cart observations and four opaque search failures; do not use it as fallback without a new decision |
| Swiggy OAuth and MCP tools | Observed once on Mohit's machine; local setup pending | Production OAuth plus `get_addresses/search_products/update_cart/get_cart`; user must reproduce locally without leaking raw PII |
| Product search | Observed once | `milk` returned in-stock products including selected Amul variant |
| Product selection | Implemented against observed shape; live local run pending | Selection uses an in-stock spin ID and enforces owner maximum budget |
| Final Swiggy quote | Observed once | ₹144 items + ₹3 handling exactly matched browser ₹147 total |
| Prava session creation | Observed once; adapter contract tested | Matching ₹147 hosted sandbox page plus a fresh API run; callback is optional and HTTPS when supplied |
| Passkey approval | Blocked/unknown | Current run showed `Verification Unavailable` before a prompt; physical-browser diagnostic required |
| Scoped credential readiness | Unknown live; memory-only handoff contract tested | Must observe `awaiting_result`; API persists only readiness/reference, never credential values |
| MCP-to-browser cart parity | Observed once | Same-account browser exactly matched item, quantity, address label, fees, and ₹147 total |
| Swiggy browser card checkout attempt | Implemented/contract-tested; unknown live | Dedicated profile with matching total and save-card disabled receives the credential once; pre-click failure is retryable, post-click ambiguity is not |
| Prava result reporting | Officially documented and contract-tested; unknown live | Confirmed decline/approval report produces expected final Prava state without repeating checkout |
| Swiggy payment/order status | Delegated; unknown | Browser order history and safe MCP reads agree on terminal decline/no order, or the run is labeled outcome-unknown |
| Merchant order confirmation | Not required for the decline demo | Real Swiggy order ID/status only after separate explicit production-purchase approval |
| Dashboard mission truth | Observed locally for the full simulated and separate staged branches | Headless action test completed create, exact approval/decline, staged creation, `PACKAGE_READY`, robot simulation, and refresh; user manual review remains |
| Robot dispatch contract | Prototype code present; integration unknown | Backend command acknowledged by navigation stack using the agreed contract |
| Hardware-free navigation core | Partially observed | 13 local core tests passed; dependency/socket gaps and all simulator/physical claims remain open; see `TEST-2026-08-01-navigation-core.md` |
| Autonomous route to pickup | Navigation-team work; not observed | Physical repeatable route evidence with measured odometry |
| Point-of-contact readiness | Planned staged event | Dashboard or tested notification route records `PACKAGE_READY` and labels it staged, not Swiggy |
| Pickup/cargo confirmation | Unknown | Agreed signal/event observed with the staged package |
| Return and completion | Navigation/hardware work | Robot returns and backend records verified completion |
| Linq notification | Unknown | Actual required events delivered with IDs/latency |
| Telegram fallback | Unknown | Same event contract passes only if fallback is selected |
| End-to-end mission | Not started | One mission ID connects every honestly labeled stage |

“Theoretically confirmed” is deliberately not “working.” Replace it only after
the manual test record exists.

## Core agent tests

At minimum cover:

- complete request;
- missing item, quantity, budget meaning, or destination;
- maximum versus exact versus range budget;
- unsupported product or merchant;
- no search results;
- unavailable variant;
- quote expiry or changed total;
- owner rejects or abandons approval;
- Prava session expires;
- merchant declines;
- merchant outcome times out or is unknown;
- duplicate request/callback/event;
- cancellation before and after each irreversible boundary;
- malicious or instruction-like merchant text;
- LLM returns invalid schema or invents fields;
- process restart during each important phase; and
- attempts to dispatch without the required gate.

## Dashboard tests

- State matches backend after refresh.
- Multiple browser tabs do not create conflicting truth.
- Sandbox, staged, simulated, and production labels are visible.
- Sensitive credentials never appear in UI, browser storage, logs, or errors.
- Approval link is tied to the correct immutable quote.
- Cancel/retry/help controls are enabled only in valid states.
- Stale robot heartbeat and provider errors are visible.
- Manual intervention appears in the event timeline.

## Payment and merchant tests

Follow `PRAVA.md`, plus:

- Swiggy OAuth/OTP never enters model context, logs, or screenshots;
- live Swiggy tool names and redacted response shapes are recorded;
- the MCP cart and normal-browser cart match exactly before approval;
- the MCP checkout tool is not called for the card-payment test;
- the browser submission side effect and order-inspection path are written before
  the Prava credential is submitted;
- amount and merchant sent to Prava match the exact quote;
- item/amount changes invalidate the old approval;
- credentials are used once and never persisted;
- merchant decline is reported as decline;
- an unknown result is inspected before retry;
- Prava and merchant IDs remain correlated;
- no real order is claimed from session creation alone; and
- no production payment occurs without explicit exact approval.

## Voice tests

- quiet and realistic noisy environment;
- different speaking speed and natural phrasing;
- interruption/barge-in;
- correction after mishearing;
- low-confidence input;
- silence/timeout;
- network loss;
- speaker output understood near robot motors;
- merchant, item, quantity, and price confirmation; and
- cancellation before payment.

Voice transcripts are data, not commands, until validated into the request
schema.

## Robot integration tests

These must be agreed with the navigation/hardware owners:

- command acknowledgement;
- invalid/unknown destination;
- duplicate dispatch command;
- route start and arrival;
- obstacle/blocked state;
- localization lost;
- network and heartbeat loss;
- emergency stop;
- pickup absent;
- cargo confirmation;
- return and dock/room arrival; and
- restart/reconnect without duplicate motion.

## Notification tests

- expected event delivered;
- provider message ID stored;
- duplicate retry does not spam;
- rate limit/auth/network failure;
- delayed or out-of-order delivery;
- inbound reply correlation if used;
- fallback activation condition; and
- dashboard remains correct when messaging fails.

## End-to-end scenarios

### Primary truthful demo

The exact scenario cannot be frozen until Phase 1. It must explicitly label:

- live Swiggy MCP discovery/cart and browser checkout versus Prava sandbox
  payment;
- Prava sandbox approval;
- expected checkout decline or genuine sandbox order result;
- the staged package and point-of-contact readiness signal;
- autonomous versus assisted navigation; and
- Linq/Telegram result.

### Required failure rehearsal

At minimum rehearse:

1. Ambiguous request stops for clarification.
2. Changed quote invalidates approval.
3. Expected sandbox merchant decline is reported correctly.
4. Robot cannot proceed or package is absent.
5. Notification provider fails while dashboard truth remains intact.

## Definition of done

A capability is done only when:

- its expected behavior and failure behavior are written;
- it passes in the intended environment;
- evidence is recorded and redacted;
- its important result is reproducible;
- the dashboard/event log tells the same story;
- docs and decision status are updated;
- secrets and sensitive data are absent; and
- the public/demo claim does not exceed the evidence.

The project is done for the software owner only when the complete scenario in
`PRODUCT.md` passes the final gate in `ROADMAP.md`.
