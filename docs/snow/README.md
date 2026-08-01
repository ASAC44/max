# Max Project Handbook

> Start here in every new chat. Read this file, then the documents listed below,
> before proposing architecture or writing code.

Planning snapshot: 1 August 2026.

This private handbook is the source of truth for planning and validating Max.
The repository's public `README.md` pitches the product; these files govern the
actual work.

## Current position

**Current work: finish the Phase 1 Prava verification/merchant attempt while
manually validating the Phase 3A agent build and its bounded live adapters.**

The user approved the product/MVP scope and execution order on 31 July 2026, so
Phase 0 passed. Zepto is rejected for this hackathon after authenticated access,
serviceability, and cart reads worked but repeated product searches returned an
opaque `Too Many Requests` error with no usable result or documented recovery;
see `TEST-VIRGIN.md`. This is a project reliability decision, not a claim that
Zepto is universally incapable.

Mohit's first run stopped at Prava `Verification Unavailable`, but Snow's later
1 August run progressed substantially further: production Swiggy OAuth, live
milk search/cart and ₹110 quote; Prava hosted card setup, OTP/passkey approval,
`awaiting_result`, and scoped credential readiness; and the dedicated browser's
exact-total/card-form fill through Swiggy's final save-or-pay confirmation. The
credential was not saved. Swiggy then rejected checkout because the selected
Work address was not serviceable; its MCP cart independently returned warning
135, order history remained empty, and Prava remained `awaiting_result`. The
Swiggy UI subsequently showed the store closed until 06:00, consistent with the
late serviceability failure. Phase 1 is therefore **verified through merchant
confirmation but not passed**: the actual merchant decline, result report, and
final Prava `failed` state still require one fresh run after the store opens.

Phase 3A now has an observed local simulated implementation under `apps/api`
and `apps/web`: 43 focused API tests pass, the Alembic migration upgrades,
downgrades, and reports no drift, the production web build succeeds, and one
simulated payment-decline mission survived an API restart with the same event
timeline. A headless browser completed every dashboard action through the
separate staged branch and refresh while preserving its mixed-environment truth
label. Live OpenAI request interpretation and most of the bounded Swiggy/Prava
path are now observed; the remaining merchant-result/report evidence is pending.
See
`TEST-2026-08-01-phase-3a-local.md`. A bounded live adapter is now implemented:
the exact observed Instamart discovery/cart/quote sequence, Prava hosted
session/polling, an operator-controlled Swiggy browser submission, and Prava
result reporting. It has mocked contract coverage but has not been run with
Swiggy OAuth or Prava secrets on this device. Scoped credentials exist only in
process/browser memory and are never returned or persisted.
The adapter now rejects Swiggy's explicit unserviceable-cart warning before
payment. The normal live UI now has one human payment checkpoint: the Prava
approval. It creates the bound session automatically, polls Prava, and then
opens a fresh Swiggy tab and follows the real cart toward payment; manual
`Check Prava status` and `Send to Swiggy` controls are recovery-only/removed.
The closed-store probe observed homepage → cart navigation and a correct
pre-payment stop. The open-store cart CTA and `Just pay` confirmation remain
live-unobserved. See
`TEST-2026-08-01-swiggy-prava-adapter.md` for exact evidence and non-claims.

Navigation has parallel implementation progress: the repository contains a
hardware-free ROS/Gazebo prototype. A minimal local check passed 13 core tests,
failed to import 2 NumPy-dependent modules, and skipped 3 socket tests in the
restricted environment; see `TEST-2026-08-01-navigation-core.md`. This is not a
Phase 6 pass: simulator criteria, measured odometry, and physical route evidence
remain outstanding.
This workstream, including its backend-to-robot bridge, is owned by the
navigation team and is not part of Snow's build schedule.

Current work order:

```text
Fix the observed Phase 3A flow/dashboard issues while the store is closed
→ after 06:00 run one fresh bounded Swiggy/Prava attempt
→ observe merchant decline → report it → verify final Prava failure
→ research and integrate voice
→ research and integrate Linq, with Telegram as backup
→ consume the navigation team's delivered interface during final integration
→ run and document the full end-to-end system
```

## Mandatory rules

1. **No assumption becomes architecture.** Mark it unknown and test it.
2. **No theoretical integration is called working.** It must run in the intended
   environment and leave reproducible evidence.
3. **No implementation begins without a defined outcome and exit gate.**
4. **Use primary sources first.** Read the live API/schema, current package,
   official repository, legal terms, and current staff answers.
5. **Separate product vision from demo truth.** Never claim a real purchase,
   merchant order, payment, pickup, or notification unless that exact event
   occurred.
6. **Separate every external stage.** Discovery, quote, approval, payment,
   merchant checkout, order confirmation, navigation, pickup, return, and
   notification are different capabilities.
7. **Prefer one verified path over several half-built paths.** Add a backup only
   where failure would end the demo.
8. **The LLM does not own money or motion.** Deterministic code and explicit
   state transitions enforce approvals, limits, dispatch, cancellation, and
   recovery.
9. **Do not expose secrets.** Never commit or print keys, cookies, OTPs,
   passkeys, card data, scoped payment credentials, addresses, or personal data.
10. **A failed experiment is evidence, not proof of impossibility.** Check setup,
    environment, permissions, versions, and official support before concluding.
11. **Update the handbook when evidence changes a decision.** Do not allow code,
    docs, and the demo story to disagree.
12. **Stop when a gate fails.** Record the failure and choose an evidenced
    fallback; do not hide it with mocks while describing the flow as real.

## Truth labels

Use these labels in research, issues, comments, and decisions:

| Label | Meaning |
| --- | --- |
| **Confirmed** | A current primary source and/or repeatable test supports it |
| **Observed** | A test produced the result, but supported scope is unclear |
| **Claimed** | A vendor, demo, post, or secondary source says it works |
| **Planned** | The team intends to build it; it is not working yet |
| **Unknown** | Reliable evidence is missing |
| **Rejected** | Tested or decided against, with a recorded reason |

Words such as “supports,” “integrates,” “works,” “secure,” “real,” and
“end-to-end” require evidence and an environment name.

## Document map and reading order

1. [`PRODUCT.md`](PRODUCT.md) — product vision, hackathon scope, user flow,
   non-goals, and success criteria.
2. [`DECISIONS.md`](DECISIONS.md) — settled decisions, candidates, open choices,
   and the rule for changing them.
3. [`PRAVA.md`](PRAVA.md) — complete payment research, limits, contradictions,
   test directions, and primary sources.
4. [`ARCHITECTURE.md`](ARCHITECTURE.md) — component boundaries, state model,
   interfaces, safety behavior, and unresolved technical choices.
5. [`ROADMAP.md`](ROADMAP.md) — execution order, entry conditions, work, evidence,
   and exit gates.
6. [`VALIDATION.md`](VALIDATION.md) — evidence standard, experiment format, test
   matrix, and definition of done.

If two documents conflict, stop. Prefer the newer recorded decision only when it
references the evidence that changed it, then correct the stale document.

## New-chat bootstrap prompt

Use this at the start of a new chat:

> Read every Markdown file in `docs/snow/`, starting with
> `docs/snow/README.md`. Treat them as the project source of truth. Before doing
> work, state the current phase, its entry condition, its exit gate, and which
> facts are confirmed versus unknown. Do not infer external capabilities from
> marketing, demos, stale docs, or memory. Research current primary sources and
> manually test where required. Do not implement beyond the current phase or
> claim an unobserved end-to-end flow.

## Updating this handbook

For each meaningful test or decision:

1. Record the experiment using the template in `VALIDATION.md`.
2. Update the relevant fact or unknown.
3. Add or revise the decision in `DECISIONS.md`.
4. Update architecture only if the evidence changes a boundary or interface.
5. Update the roadmap gate.
6. Check the product/demo claims for accuracy.

Do not create speculative documents “for later.” Add a document only when it
has a distinct job that the current handbook cannot perform cleanly.
