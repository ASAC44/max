# Prava Research

> Research snapshot: 1 August 2026. Prava is changing quickly. Recheck current
> official sources before making architectural or product claims.

This dossier is part of the private Max handbook. Start with [`README.md`](README.md)
for the governing workflow and evidence rules.

This document records what is known about Prava, what remains uncertain, and
how future research for Max must be conducted. It is research context, not the
final Max architecture.

## Instructions for future agents

Treat payment claims as high-risk and time-sensitive.

1. Do not guess. If a capability is not explicitly documented or successfully
   tested, label it **unverified**.
2. Start with current primary sources: the live API/OpenAPI reference, published
   packages, the main official GitHub branch, legal pages, and written answers
   from Prava staff.
3. Search broadly when needed. Check the documentation index, API schema,
   package contents, repository history and branches, changelog, handbook,
   merchant list, legal pages, and the relevant merchant or protocol's own
   documentation.
4. Do not treat search-engine snippets, old indexed pages, social posts, demo
   videos, or feature branches as proof that a feature is publicly available.
5. Separate these four labels in every conclusion:
   - **Confirmed:** current primary source or repeatable test proves it.
   - **Observed:** seen in a test, but the supported scope is not documented.
   - **Claimed:** Prava marketing, social media, or a demo says it works.
   - **Unknown:** no reliable answer yet.
6. Separate sandbox support from production support. A sandbox test never proves
   that Indian users, Indian-issued cards, a particular network, or a production
   merchant is supported.
7. Separate product discovery, cart creation, payment approval, merchant
   checkout, order confirmation, and physical fulfilment. Success in one stage
   does not prove the next stage.
8. Quote exact API state names and inspect the current schema. Do not paraphrase
   money-state transitions from memory.
9. Never expose API keys, card data, scoped credentials, OTPs, passkeys, cookies,
   or personal addresses in prompts, logs, commits, screenshots, or reports.
10. Do not attempt a real charge, link an account, enroll a real card, or create
    production state without the user's explicit approval. Read-only research
    and sandbox tests are safer defaults.
11. When sources conflict, present the conflict. Prefer the current API schema
    for API mechanics, current legal terms for availability and restrictions,
    and current package contents for SDK/CLI behavior.
12. Record the date, environment, package version, endpoint, input class, result,
    and evidence for every manual test. A failed test may mean bad setup; it does
    not automatically prove a capability is unsupported.

## Core mental model

Prava is a permission and credential layer for agentic card payments.

```text
Agent or app builds an exact purchase
                ↓
Prava asks the cardholder to approve it
                ↓
Prava issues a scoped, short-lived card credential
                ↓
An agent, app, or Prava shopping service uses it at merchant checkout
                ↓
The merchant's normal PSP/acquirer processes the card payment
                ↓
The checkout result is reported to Prava
```

Prava does not hold or transfer the user's money. Its terms say it is not a
bank, issuer, acquirer, payment processor, money transmitter, stored-value
provider, or deposit-taking institution. Banks, card networks, merchant payment
providers, and other regulated parties handle authorization and money movement.

Prava therefore solves:

- card enrollment and secure vaulting;
- user approval through a passkey;
- agent authorization;
- merchant- and amount-scoped payment credentials;
- single-use credentials and spending controls;
- payment-session state and reporting;
- mandates for repeated controlled purchases; and
- optional product-search and checkout flows for supported commerce sources.

Prava does not automatically solve:

- product discovery at every merchant;
- cart and quote creation at every merchant;
- arbitrary website navigation;
- merchant card acceptance;
- order fulfilment or delivery;
- UPI QR, card-to-UPI conversion, cash, bank transfer, or P2P payment; or
- paying a canteen worker, delivery rider, or classmate directly.

## Integration surfaces

Prava currently documents three paths.

| Path | Intended use | User interface | Credential handling | Environment |
| --- | --- | --- | --- | --- |
| Embedded SDK + API | A custom application | Secure Prava iframe inside the app | Backend can receive scoped credentials | Sandbox and production |
| Hosted API | A custom application with minimal payment UI | Redirect to Prava's hosted page | Backend can receive scoped credentials | Sandbox and production |
| Prava Pay MCP or CLI | Existing AI-agent platforms | Prava-hosted account and approval flow | MCP keeps credentials server-side; CLI may return them to the local agent | Public hackathon material describes this as production-oriented |

### SDK and REST API

The current `@prava-sdk/core` package is small. Its real public frontend job is
secure card collection through `collectPAN()` and cleanup through `destroy()`.
The backend still creates and monitors sessions through REST.

Old pages containing SDK methods such as `registerIntent`, `invokeIntent`,
`updateIntent`, or `deleteIntent` are stale. Prava's own documentation roadmap
says fictional methods were removed.

Current public REST operations include:

- `POST /v1/sessions`
- `POST /v1/sessions/{id}/revoke`
- `GET /v1/listCards`
- `POST /v1/deleteCard`
- `GET /v1/sessions/{id}/payment-result`
- `POST /v1/sessions/{id}/report-status`
- mandate charge, report, list, get, pause, resume, and cancel operations

The public REST schema does not expose a general product-search, browser-harness,
or arbitrary merchant-checkout API. Those belong to other Prava Pay services or
must be built by the integrator.

### MCP

The hosted MCP endpoint is `https://mcp.pay.prava.space/mcp`. It uses OAuth and
exposes payment, shopping, address, card, agent, and mandate-management tools.

The current tool reference includes tools for:

- creating and checking payment sessions;
- searching products, reading product details, getting quotes, and checking out;
- listing and managing saved delivery addresses;
- listing cards and linked agents; and
- creating, listing, reading, pausing, resuming, and cancelling mandates.

MCP uses a credential firewall: the AI agent should not see the temporary card
number or CVV. One unresolved gap remains: the public tools explain
`shop_checkout` for Prava's supported shopping flow, but do not clearly explain
who executes an arbitrary known-merchant checkout when the credential stays
hidden. This matters only if Max chooses MCP plus a generic merchant.

### CLI

The current CLI package is `@prava-sdk/cli`. The live service was observed on 31
July 2026 requiring CLI version 3.1.0 or newer and skill version 2.2.0 or newer.
Recheck before installation.

The CLI supports agent linking, payment sessions, shopping, reporting, and
mandate charging. Unlike MCP, a direct CLI payment flow may print the scoped
token and cryptogram for the local agent to use at checkout.

Important limits:

- one linked agent identity is stored per machine;
- agent state is sensitive;
- the account owner controls cards and addresses;
- current public docs do not show a detailed per-agent card permission matrix;
- shopping quote and checkout calls may take tens of seconds; and
- a checkout with an unknown result must not be blindly retried.

## Exact one-time REST payment flow

1. The application first knows the merchant, products, final amount, currency,
   and user.
2. Its backend calls `POST /v1/sessions` with one purchase context.
3. Prava returns a session token and hosted/iframe URL. Sessions expire after
   approximately 15 minutes.
4. The user opens Prava's secure surface, enrolls or selects a card, and approves
   with WebAuthn/passkey. First-time card enrollment may also require issuer OTP
   verification.
5. The backend polls `GET /v1/sessions/{id}/payment-result`.
6. The current API reference says `token`, `dynamic_cvv`, and expiry fields are
   present when the state is `awaiting_result`.
7. The application or agent uses that credential like a normal card at the
   specified merchant checkout.
8. The backend calls `POST /v1/sessions/{id}/report-status` with `APPROVED` or
   `DECLINED`.
9. Prava then records the final `completed` or `failed` state.

Creating a session or obtaining user approval is not an order. The merchant
checkout still has to be attempted, and an order is real only when the merchant
confirms it.

### Documented session constraints

- One purchase context means one merchant per session.
- A multi-merchant or split payment is not documented.
- Merchant URL and callback URL use HTTPS.
- Amounts are decimal strings with up to two decimal places.
- At least one product is required.
- Shipping, tax, and fees may be included in the final total.
- The API supports many ISO currencies, including INR, but currency support does
  not prove production cardholder or regional availability.
- Credentials are described as single-use and short-lived. An exact canonical
  credential lifetime is not currently documented.
- The API returns an `X-Response-ID`; preserve it when reporting failures.

## Shopping, UCP, and merchant checkout

Prava Pay adds a shopping layer above payment:

```text
search → product → quote → approval → checkout
```

For physical goods, the owner's address and phone are stored by Prava and
hydrated server-side. The agent receives a masked address summary rather than
the complete details.

### Shopify and UCP

Prava's documented shopping flow is currently strongest around Shopify and UCP
(Universal Commerce Protocol). UCP can expose catalog, cart, checkout,
fulfilment, and order capabilities. A merchant may still require authentication
or send the buyer to a `continue_url` for review.

Prava's Browser Harness is documented as completing Shopify checkout after UCP
discovery and quote creation. It can reconcile tax or shipping changes before
payment. Public documentation does not prove that this harness works on every
merchant website or that SDK/API users can call it directly.

“Works with any merchant or PSP” should be read narrowly: a scoped credential
looks like card details that a normal card form may accept. It does not mean
Prava can search, navigate, and complete every merchant checkout automatically.

### Other merchant sources

The hackathon merchant list contains Shopify merchants, Indian UCP merchants,
travel and experience MCPs, and several Claude connectors. It is a discovery
resource, not a compatibility guarantee.

For every candidate merchant, independently verify:

1. Can the agent search the real catalog?
2. Can it select a real variant and quantity?
3. Can it build a cart?
4. Can it obtain the final payable total, including tax and delivery?
5. Can the checkout accept card details or a compatible payment instrument?
6. Can the agent or user reach that checkout legally and reliably?
7. Can the merchant return a final success, decline, or order identifier?

Some listed MCPs only search and return an affiliate or booking link. Discovery
alone is not an end-to-end transaction.

### Rejected merchant: Zepto MCP

The official Zepto MCP at `https://mcp.zepto.co.in/mcp` was investigated as
Max's commerce source. Its official material describes:

- an Indian Zepto account authenticated by mobile number and OTP through OAuth;
- live catalog search with availability and prices;
- cart add, update, and remove behavior synchronized with the Zepto account;
- order placement and order-history/status access;
- card payments through a secure online checkout flow; and
- a production-only environment in which any placed order is real.

The live endpoint was checked read-only on 1 August 2026. It returned the
expected unauthenticated `401`, advertised OAuth resource metadata, and pointed
to `https://auth.zepto.co.in`. The authorization server publishes authorization,
token, dynamic-registration, PKCE, and refresh-token metadata. This confirms a
standards-based connection surface, not that the team's account or client works.

Zepto's engineering article says online payment creates a short-lived URL for a
specific order and the user completes payment there. Current public material
does not specify whether requesting that URL creates a pending order, whether a
preview action is available, the exact current MCP tool names, or how a failed
card attempt is represented. Those details must be observed before automation.

Prava's current Dining page says food delivery is already possible through
merchant skills such as Zepto paired with Prava Pay. A historical official
`zepto-prava-skill` gave a concrete flow: preview with `confirmOrder: false`,
mint the exact Prava credential, create the short-lived Zepto/Juspay link with
`confirmOrder: true`, enter the tokenized card in a controlled browser, and poll
payment status. However, Prava removed that wrapper from the current
`prava-skills` main branch on 23 July 2026 in a commit titled “separate merchant
skill from main skill.” It is **Claimed/historical evidence**, not a package Max
will install or an API contract Max may assume.

The team then authenticated successfully, listed 23 live tools, selected a
serviceable store, and read an empty cart. Four exact product-search attempts
returned only `Too Many Requests`; the wrapper provided no structured upstream
status, retry window, product result, or documented recovery. The experiment is
recorded in `TEST-VIRGIN.md`.

**Rejected for the hackathon on 1 August 2026:** the failure does not prove that
Zepto search never works, but it makes this provider too unreliable for the
remaining project schedule. Do not retry or restore Zepto as a fallback without
a new explicit decision.

### Active candidate: Swiggy Instamart MCP plus browser

The current Phase 1 candidate separates commerce from card entry:

```text
Swiggy Instamart MCP: auth → address → search → product → cart → quote
normal Swiggy browser: verify identical cart → fresh card form → submit once
Prava SDK/API sandbox: approval → scoped credential → report result
```

The MCP checkout tool is excluded from this test because the documented grocery
checkout path does not provide the required card-entry route. The browser is not
assumed to be a reliable automation surface: Mohit must prove same-account cart
continuity, exact totals, an unsaved-card form, the merchant result, and order
history before Max adopts it.

Detailed execution and evidence instructions live in `docs/mohit/DIRECTIONS.md`
and `docs/mohit/DOCUMENTATION_TEMPLATE.md`. Mohit's first run observed the
commerce subset and stopped at hosted verification. Snow's later 1 August run
observed Prava card setup, OTP/passkey, `awaiting_result`, scoped credential
readiness, and browser entry through Swiggy's final save-or-pay confirmation.
The store then became unavailable before a merchant payment result. The combined
path is therefore observed substantially further but still not complete.

## Sandbox and hackathon interpretation

The SDK/API sandbox provides test keys, test cards, test OTP, session lifecycle,
and a real WebAuthn/passkey interaction without moving real money. Sandbox
success proves the integration logic; it does not prove production eligibility,
merchant acceptance, or support for Indian-issued cards.

The hackathon guidebook says a transaction must be completed or enabled and that
a payment session alone is not a completed order. Prava staff gave the team a
more specific judging instruction in Discord:

1. obtain the final one-time sandbox credential;
2. try it at the merchant's checkout;
3. the merchant payment is expected to fail because the credential is sandboxed;
4. show the failed payment screen; and
5. report the decline back to Prava.

According to that staff answer, this failed merchant attempt counts as a complete
transaction for hackathon judging. Preserve the original message or screenshot;
it is stronger evidence than a paraphrase in this file.

The guidebook describes SDK/API as the recommended hackathon path and MCP/CLI as
production paths. Do not assume Prava Pay shopping or Browser Harness has a
sandbox until it is observed or confirmed.

## Production, regions, and payment rails

Prava's Terms, updated 6 July 2026, say the service is currently intended for
users in the United States. Production availability depends on the network,
issuer, merchant, PSP, partners, law, and compliance. SDK/API production also
requires business verification; sandbox does not.

Therefore none of these are currently proven by an ordinary sandbox test:

- production access for an India-based team;
- support for an Indian-issued Visa card;
- production support for Mastercard or another card network;
- a successful charge at an Indian merchant; or
- production use by a person under 18.

The public sandbox currently documents Visa test cards. Legal and marketing pages
mention other networks “where applicable,” which is not proof that they are live
for this account or region.

Using Prava does not require a separate Visa Intelligent Commerce integration.
Prava is the layer integrating with Visa's agentic-commerce capabilities where
available. Visa Trusted Agent Protocol is a separate agent-identification and
web-request-signing concept; it does not guarantee that every merchant permits
automation or accepts a purchase.

### Not currently supported for Max

- merchant UPI QR;
- Credit Card on UPI;
- card-to-UPI conversion;
- arbitrary bank transfer;
- P2P transfer to a classmate;
- paying a delivery worker's personal QR; and
- cash handling.

This conclusion matches both the public documentation and the direct Prava team
reply received by the Max team. Do not claim future or undocumented UPI support.

## Mandates

A mandate is advance permission for later charges inside approved limits. It can
bind merchant, maximum amount, frequency, duration, use count, and purpose.

Documented forms include one-time, weekly, monthly, and yearly. The user approves
the mandate once; the agent later initiates each allowed charge without a fresh
passkey. Prava does not currently schedule and run subscriptions automatically.

Relevant limits include:

- one-time mandates have a short maximum validity;
- recurring mandates are merchant-specific;
- amount caps are enforced;
- the mandate can be paused, resumed, cancelled, consumed, or expire; and
- cancellation is terminal.

Current MCP tools manage mandates but do not expose mandate charging; REST and
CLI do. Documentation is inconsistent about whether `max_charges` is a strict
maximum or an advisory hint. Confirm before relying on it.

Mandates are unnecessary for the first Max demo unless repeated autonomous
purchases become part of the explicit scope.

## Guardrails and security

Hard controls can technically stop a payment:

- passkey approval;
- merchant binding;
- amount cap;
- one-time credential;
- expiry;
- mandate restrictions; and
- agent revocation.

Soft controls are instructions to the language model, for example “always ask
before buying” or “choose the cheapest delivery.” A skill or prompt is not a
cryptographic restriction. The payment design must rely on hard Prava controls
for money authorization.

Prava states that raw card numbers and CVV do not live in its application
database and that vaulting uses a PCI-compliant provider. Approved agents or
browser automation may still receive scoped payment credentials. Developers must
not store, log, expose, or misuse them.

Prava collects and processes account, authentication, payment, checkout, agent,
OAuth, fraud, support, usage, and diagnostic data. It may share necessary data
with networks, banks, PSPs, processors, vault providers, merchants, cloud and
security providers, and connected applications. Its privacy policy does not give
a simple fixed retention period.

Restricted categories include gambling, weapons, tobacco or nicotine,
prescription-only drugs, crypto and wallet funding, P2P or wire transfer, account
funding, financial trading, adult services, and other illegal or prohibited use.

## Operational limits and risks

- A merchant, issuer, fraud system, PSP, 3DS flow, or network may decline a valid
  Prava credential.
- Product availability, shipping, and tax can change after discovery.
- Browser automation can break when a merchant changes its page or blocks bots.
- Prava does not guarantee acceptance by every merchant or uninterrupted service.
- Public docs mention quotas and concurrency controls without documenting exact
  values.
- Public REST usage is polling-based. Webhook references exist, but dependable
  public webhook delivery is not yet verified.
- A payment with an unknown merchant result must not be automatically retried;
  first check the merchant order/payment state to avoid duplicate purchases.
- Refund documentation is inconsistent: one page says API refunds exist, but the
  current public API schema does not show a clear refund endpoint. Assume the
  merchant's normal refund system unless Prava confirms otherwise.
- Settlement and chargebacks remain standard merchant, bank, and card-network
  processes.

## Known documentation conflicts

Do not hide these conflicts in future answers:

1. Search engines still expose stale SDK intent pages; the real current SDK is
   primarily `collectPAN`.
2. The current payment-result reference exposes credentials at
   `awaiting_result`; some integration text incorrectly waits for `completed`.
3. One page says a standard session “charges immediately,” while the lifecycle
   requires a separate merchant checkout.
4. Marketing can imply universal merchant support, while the documented Browser
   Harness is currently Shopify-focused.
5. Prava docs mention Zepto merchant skills, but the Zepto-specific wrapper was
   removed from the current public `prava-skills` main branch.
6. “No OTP” messaging conflicts with card-enrollment documentation that allows
   issuer OTP verification.
7. Refund API support is claimed without a current public refund endpoint.
8. Marketing and older FAQ statements about networks, UPI, and regions do not
   cleanly match the current legal terms and test-card docs.
9. Exact token lifetime, quota, and concurrency limits are not public.
10. MCP's generic known-merchant checkout executor is not clearly documented.
11. Changelog tool counts and skill versions have lagged behind current docs and
    live server requirements.
12. A successful social-media demo is not proof of a released API, skill,
    sandbox, or supported production region.

## Meaning for Max

Prava can support this direction:

```text
voice or message request
→ agent searches Swiggy Instamart through its official MCP
→ agent builds a cart and gets the final total
→ normal Swiggy browser shows the identical cart and card form
→ user approves through Prava
→ card checkout is attempted
→ Swiggy returns payment/order status
→ a separately valid handoff signal permits robot travel
→ robot collects the real or explicitly staged package
→ robot returns to its owner
```

Prava cannot currently support this direction:

```text
robot meets an arbitrary person
→ person shows a UPI QR
→ robot uses Prava to pay the QR
```

Swiggy MCP belongs to the discovery/cart layer. The normal Swiggy browser is the
candidate checkout layer. Prava belongs to approval and scoped card payment. The
robot belongs to a separate physical handoff layer. Keep them separate in the
architecture and demo claims.

## Open questions and priority

### Must answer through manual testing or staff before final scope

1. **Swiggy tool contract — partly answered:** production Instamart exposed and
   successfully ran address, search, cart update, and cart read operations. Raw
   cart results contain full address/mobile/coordinates; read-only order status
   still needs safe observation.
2. **Browser Harness access — answered:** Prava staff confirmed it is only for
   MCP/CLI. SDK/API applications must implement their own UCP integration.
3. **MCP/browser continuity — observed once:** the normal browser exactly matched
   the ₹147 cart and exposed a new-card option; reproduce on the user's account.
4. **SDK/API checkout handoff:** Can the Prava sandbox token, cryptogram, and
   expiry be entered once in that form and return the expected visible decline
   without creating a successful real order?
5. **Order side effect:** How do browser order history and safe MCP status reads
   prove that the attempt did not create a successful order?

### Latest support response

**Confirmed, 31 July 2026:** Prava staff followed up that Browser Harness is only
available for MCP/CLI. An SDK/API application must implement its own UCP
integration. Preserve the original reply as primary evidence. This confirms the
integration boundary, not that Max's UCP or merchant checkout works.

**Confirmed from the published `@prava-sdk/cli` 3.1.0 package:** the bundled
shopping flow explicitly chains `shop search → product → quote`, a Prava
payment session, and Browser Harness checkout. This is the MCP/CLI alternative,
not an SDK/API shopping surface and not required for the selected Swiggy path.

**Observed, 1 August 2026:** Zepto authentication, tool listing, serviceability,
and cart reads worked, while four product searches failed opaquely. **Rejected
for this project:** no further Zepto work is scheduled. This is a reliability/
time decision, not a universal capability claim.

**Observed/inconclusive, 1 August 2026:** Mohit's Swiggy OAuth, milk search,
cart mutation, ₹147 quote, browser parity, new-card option, and hosted Prava
session creation worked. The page then displayed `Verification Unavailable`
before card fields or a passkey prompt. This is not a decline and does not pass
Phase 1.

**Observed/inconclusive, later 1 August 2026:** Snow's fresh-device run passed
hosted card setup, OTP/passkey approval, `awaiting_result`, scoped credential
readiness, and browser card entry. Swiggy then returned an unserviceable Work
address error; MCP independently returned cart warning 135, no order existed,
and Prava remained `awaiting_result`. The Swiggy UI showed the store closed until
06:00. This is evidence through merchant confirmation, not a card decline. One
fresh run after reopening must still prove the terminal merchant result and
Prava result-report/final-state loop.

Current official hosted-mode guidance requires `integration_type:
"full_checkout"`, an HTTPS `callback_url`, and the returned `iframe_url` used
verbatim. Sandbox uses real WebAuthn on a supported browser. The follow-up must
check session freshness, those request fields, secure-context/WebAuthn/platform-
authenticator booleans on a physical normal browser, then give Prava the
redacted session/response ID if the error repeats. No public error reference
maps the exact screen to a single root cause, so do not claim one yet.

### Conditional questions

- **Credential state:** required if Max uses SDK/API. Follow the current API
  reference (`awaiting_result`) and verify it in sandbox.
- **Exact token TTL, quota, and concurrency:** usually not scope-defining for the
  hackathon MVP, but record observed values if they cause a test failure.
- **India production eligibility:** not a hackathon blocker because the accepted
  demo uses sandbox credentials and an expected merchant decline. Revisit only
  if Max later needs real production purchases with an Indian-issued card.

## Manual exploration plan

Use the smallest test that answers one question at a time.

### Phase 1: Read-only inventory

1. Read the current documentation index and integration chooser.
2. Inspect the current REST/OpenAPI schema, not old indexed pages.
3. Check current NPM versions and actual exported package APIs.
4. Check the main `prava-docs` and `prava-skills` branches plus relevant recent
   commits and branches.
5. Read current Terms, Privacy, Security, hackathon guidebook, and merchant list.
6. Record the date and versions in the test log.

### Phase 2: SDK/API sandbox

1. Create a developer sandbox account and obtain test keys.
2. Keep the secret key on the backend; never place it in frontend code or commit
   it.
3. Create the smallest one-product, one-merchant test session.
4. Open the hosted Prava URL first. This tests the payment flow without SDK UI
   complexity.
5. Complete test-card entry, OTP if required, and passkey approval.
6. Poll the payment result and record the exact state transition.
7. Confirm whether credentials appear at `awaiting_result`.
8. Use the reviewed Swiggy browser cart/checkout from Phase 3 for the sandbox card
   attempt; do not improvise another merchant.
9. Record the merchant failure and report `DECLINED` to Prava.
10. Confirm the final Prava state and save redacted evidence.

This phase can verify the REST flow and judging transaction. It does not need to
verify an Indian production card. It also cannot prove MCP/CLI shopping support.

### Phase 3: Delegated Swiggy commerce path

Mohit follows `docs/mohit/DIRECTIONS.md`; that file is canonical when this
summary differs.

1. Connect an MCP-capable client and complete Swiggy OAuth/OTP outside model
   context. Record versions, live tool names, and redacted response shapes.
2. Select a serviceable saved address and one cheap non-restricted product.
   Reproduce search, product/variant, cart mutation, quote, fees, currency, and
   ETA through the MCP.
3. In a normal browser logged into the same account, verify the identical cart,
   address label, quantities, and total. Stop if they differ.
4. Verify that browser checkout offers an unsaved credit/debit-card form. Do not
   call the MCP checkout tool and do not use a real card.
5. Run the hosted Prava SDK/API sandbox flow bound to that exact Swiggy cart and
   total. Keep the credential only in controlled process/browser memory.
6. Recheck all purchase fields, disable save-card, and submit the sandbox
   credential exactly once.
7. Record the visible result, inspect browser order history and safe MCP status,
   and classify any timeout as unknown rather than retrying.
8. Only after a confirmed decline, report `DECLINED` to Prava and verify final
   `failed`.
9. Return the completed `docs/mohit/DOCUMENTATION_TEMPLATE.md` and redacted
   evidence to Snow.

### Phase 4: Decision after the Swiggy test

- If Swiggy MCP → identical browser cart → Prava approval → browser decline →
  Prava failure is reproducible, pass Phase 1 and freeze only the observed
  tool/browser contract.
- If discovery/cart works but browser cart continuity or card entry fails,
  reject the combined path and decide whether the demo claim can be reduced.
- If the merchant result is unknown or a real order appears, stop, preserve the
  evidence, resolve it through legitimate status/support paths, and do not retry.
- Zepto and Shopify/UCP remain rejected from the active plan unless the user
  explicitly reopens either decision.

### Phase 5: Post-hackathon production boundary

Skip this phase for the current hackathon demo. If Max later needs real purchases,
production testing requires explicit user approval and Prava eligibility. Before
any attempt, confirm user/card region, network, merchant country, legal/business
verification, expected real charge, refund method, and spending limit. Do not
infer production support from sandbox behavior.

## Primary sources

- [Prava documentation](https://docs.prava.space/)
- [Choosing an integration](https://docs.prava.space/choosing-your-integration)
- [Payment lifecycle](https://docs.prava.space/concepts/payments)
- [Get Payment Result](https://docs.prava.space/api-reference/get-payment-result)
- [Sandbox testing](https://docs.prava.space/api-reference/testing)
- [MCP tools](https://docs.prava.space/mcp/tools)
- [Agentic shopping](https://docs.prava.space/prava-pay/shopping)
- [Dining and food-delivery status](https://docs.prava.space/integration/dining)
- [UCP integration](https://docs.prava.space/integration/ucp)
- [Mandates](https://docs.prava.space/concepts/mandates)
- [Compliance and verification](https://docs.prava.space/guides/compliance)
- [Prava Terms](https://www.prava.space/terms-conditions)
- [Prava Privacy Policy](https://www.prava.space/privacypolicy)
- [Prava Security](https://www.prava.space/security)
- [Prava docs repository](https://github.com/Prava-Payments/prava-docs)
- [Prava docs roadmap](https://github.com/Prava-Payments/prava-docs/blob/main/ROADMAP.md)
- [Prava skills repository](https://github.com/Prava-Payments/prava-skills)
- [Official Zepto MCP](https://github.com/zeptonow/mcp)
- [Zepto MCP engineering article](https://blog.zepto.com/how-zepto-enables-seamless-shopping-through-ai-fcc7d2e43c7b)
- [Historical Zepto-Prava wrapper](https://github.com/Prava-Payments/prava-skills/blob/df1c32cbfd5ecb7d1ce2647b621e95ee5f3741a7/prava-merchants-checkout/zepto-prava-skill/SKILL.md)
- [Swiggy Instamart MCP reference](https://mcp.swiggy.com/builders/docs/reference/instamart/)
- [Swiggy grocery recipe](https://mcp.swiggy.com/builders/docs/build/recipes/order-groceries/)
- [Swiggy Instamart checkout](https://mcp.swiggy.com/builders/docs/reference/instamart/checkout/)
- [`@prava-sdk/core`](https://www.npmjs.com/package/@prava-sdk/core)
- [`@prava-sdk/cli`](https://www.npmjs.com/package/@prava-sdk/cli)
- [Official hackathon guidebook](https://docs.google.com/document/d/e/2PACX-1vRg9zmj3a5aWqUJQUaLDT4_SEUQGzt9lGn8aYVC898PTYOFIE3loLW_gCg0aEn334FogipRadhuNyju/pub)
- [Hackathon merchant list](https://docs.google.com/spreadsheets/d/1Vwqybz1P9pNz3aQXc8Q4uVqa1p7vYTu_y3ySC7Xsunw/edit?gid=890707389)
- [Visa Intelligent Commerce](https://www.visa.com/en-us/solutions/intelligent-commerce)
- [Visa Trusted Agent Protocol](https://developer.visa.com/capabilities/trusted-agent-protocol/trusted-agent-protocol-specifications/)
