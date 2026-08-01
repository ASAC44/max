# Test: bounded Swiggy and Prava adapter

- Date/time and timezone: 1 August 2026, Asia/Kolkata
- Operator: Snow/Codex
- Goal/question: Can the main API encode Mohit's observed boundary and a
  fail-closed one-shot checkout bridge without claiming a live result?
- Required decision/gate: safe partial integration; not a Phase 1 exit
- Environment: local tests with provider transports mocked
- Hardware/device/browser/network: local development machine; no provider login
- Service/package/API versions: MCP Python 1.29.0; current Prava REST docs checked
- Account/access class: no Swiggy OAuth or Prava secret configured locally
- Primary documentation checked: current Prava create-session, integration-mode,
  sandbox-testing, payment-result, report-status, and developer FAQ pages; Mohit's
  dated production Swiggy/Prava record

## Preconditions

- Mohit's record proves the production Instamart address/search/cart/quote
  subset and hosted Prava session creation once.
- The Prava hosted page failed before credential readiness.
- No scoped credential may enter the model, response, database, logs, or tests.

## Exact steps

1. Rebased the reviewed Phase 3A implementation onto Mohit's remote commit.
2. Added a deterministic Instamart MCP adapter limited to address selection,
   empty-cart check, product search, spin-ID cart update, and final cart read.
3. Reduced raw MCP output to quote-safe fields; added a sentinel PII test.
4. Added hosted Prava create-session using `full_checkout`, optional HTTPS callback, exact
   amount/line items, and sandbox-only secret validation.
5. Added payment-result polling that returns only state, transaction reference,
   and a credential-fields-present boolean.
6. Added a dedicated Chromium/CDP bridge that verifies total, disables card
   saving, clears fields, submits once, and never retries an unknown result.
7. Added confirmed merchant-result reporting and separate report recovery.
8. Ran the complete API/agent/workflow suite and web production build.

## Expected result

- Live modes can reach an immutable Swiggy quote and hosted Prava action without
  granting the LLM checkout tools or exposing credential values.
- Merchant checkout is code-complete for the one demo path but live-unobserved.

## Observed result

- `39 passed` in 4.39 seconds; web production build passed.
- The mocked live API path reached `PAYMENT_APPROVAL_REQUIRED`, returned a safe
  hosted action, reached `PAYMENT_PERMISSION_READY`, recorded a browser decline,
  reported it, and reached Prava `failed`/mission `PAYMENT_DECLINED`.
- Tests confirmed exact ₹147 Prava line-item total and absence of session token,
  network token, expiry, and dynamic CVV from application output/persistence.
- The live Swiggy MCP probe could not initialize because this OS user has no
  configured Swiggy MCP/OAuth entry, matching the user's later clarification.

## Evidence

- `apps/api/tests/test_integrations.py`
- `apps/api/tests/test_api.py::test_live_provider_boundary_is_wired_without_exposing_credentials`
- `apps/api/tests/test_workflow.py::test_prava_hosted_flow_stops_before_merchant_checkout`
- Mohit's `docs/mohit/tests/2026-08-01-swiggy-prava.md`

## Deviations and interventions

- No live provider call was attempted because credentials/OAuth are not set up
  on this device.
- Stripe code delivered in the remote robot commit was reviewed, found unrelated
  to the agreed Prava architecture, and removed with its robot endpoints, tests,
  config, and demo document. It remains recoverable in Git history.

## Conclusion

- **Observed** for the local bounded adapter contract; **unknown** for live use
  from this device; **inconclusive** for Phase 1 payment.
- What this proves: application state, redaction, one-shot guards, and result
  reporting agree under contract tests.
- What this does not prove: local Swiggy OAuth, live MCP response compatibility,
  Prava hosted verification, credential readiness, browser entry, decline, or
  final result reporting.
- Follow-up: configure local OAuth, run a cheap quote, then repeat Prava hosted
  verification with the diagnostic checklist.
- Documents/decisions updated: README, ROADMAP, DECISIONS, ARCHITECTURE, PRAVA,
  VALIDATION, public Swiggy plan, API README, and Mohit directions/record.

## Live continuation — Snow's device

- **Observed:** live OpenAI interpretation; Swiggy MCP OAuth, milk search, cart
  mutation, ₹110 total, saved Work-address selection, and browser parity; Prava
  hosted card setup, OTP/passkey approval, exact transaction-reference match,
  `awaiting_result`, and credential readiness.
- **Observed:** the CDP browser bridge matched the approved total, required the
  manually entered cardholder name, disabled card saving, filled the scoped
  credential, and reached Swiggy's final `Save card and pay` / `Just pay`
  confirmation. The operator chose the save option during diagnosis, but Swiggy
  did not persist the card.
- **Observed failure:** Swiggy then displayed `The selected address is not
  serviceable at the moment`. A read-only MCP cart check independently returned
  Work address warning `statusCode: 135` with the instruction not to proceed;
  `get_orders` returned zero orders. The Swiggy UI later showed the store closed
  until 06:00, consistent with the warning.
- **Safety result:** Max recorded `CHECKOUT_OUTCOME_UNKNOWN`, disabled retry,
  did not report a false decline, and Prava remained `awaiting_result` for the
  exact transaction.
- **Correction:** quote creation and the immediate pre-submit recheck now reject
  an explicit unserviceable-cart warning. The browser bridge now selects only
  `Just pay`. `43 passed`; the latter click remains live-unobserved.
- **Gate status:** verified through merchant confirmation, not end to end. A
  fresh post-06:00 run must still observe the merchant result, result detection,
  Prava result reporting, and final Prava `failed`/`completed` state.

## Flow correction after the live run

- The prior dashboard exposed debugging transitions as normal user actions.
  Live quote/session setup now proceeds directly to the bound Prava approval;
  that passkey approval records the exact quote authorization.
- The dashboard polls Prava automatically and invokes checkout once when scoped
  permission becomes ready. Manual status-refresh and merchant-submit buttons
  are absent from the normal path; a pre-submit browser retry remains only for
  exceptional recovery.
- The dedicated browser now opens a fresh Instamart tab, follows the observed
  homepage cart control into `/instamart/cart`, rejects closed/unserviceable
  state, and is prepared to select the live checkout CTA, open `Add New Card`,
  fill the configured cardholder name, disable saving, and choose `Just pay`.
- **Observed while closed:** fresh homepage and cart navigation, exact current
  cart, and a safe stop before payment. A direct `/payment` jump was rejected as
  an implementation strategy because it visibly produced `Delivering to: null`.
- **Still unobserved:** the checkout CTA available only while the store is open,
  its address-carrying payment transition, automatic `Just pay`, and the
  terminal merchant/Prava result loop.
