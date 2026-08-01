# Test: Swiggy Instamart MCP + Browser + Prava Sandbox

> Copy this file to a dated test record and fill it during the test. Never enter
> phone numbers, OTPs, complete addresses, coordinates, OAuth tokens, cookies,
> API secrets, passkeys, network-token values, expiry values, or cryptograms.

## Test identity

- Date/time and timezone: 2026-08-01,
- Operator: Mohit
- Goal: Validate Swiggy Instamart MCP → browser card checkout → Prava sandbox
  decline → Prava final failure.
- Required decision/gate:
- Environment: mixed — Swiggy production account/cart, Prava sandbox payment
- Hardware/device/browser/network:
- Codex/MCP client version: codex-cli 0.146.0
- Node version: v26.5.0
- `mcp-remote` version: latest (npx --yes, unpinned)
- Prava API/SDK version:
- Account class: authenticated Swiggy account; no phone number
- Primary documentation checked:

## Preconditions

- [x] Saved Swiggy address exists
- [x] Instamart is serviceable
- [ ] Browser is logged into the same account
- [ ] Prava sandbox access is available
- [ ] Test product is non-restricted and low risk
- [ ] Expected cart is approximately ₹100–₹200 and below ₹1,000
- [ ] Expected final outcome is merchant decline
- [ ] Sensitive-data storage locations have been checked

## Expected result

```text
Swiggy MCP search/cart succeeds
→ browser displays the identical cart and a new-card form
→ Prava approval reaches credential-ready state
→ credential is submitted once
→ Swiggy declines without creating a real order
→ Prava accepts DECLINED and reaches failed
```

## MCP setup and authentication

### Expected

-

### Observed

-

### Evidence

- Redacted MCP configuration result: `codex mcp add swiggy-instamart -- npx --yes mcp-remote https://mcp.swiggy.com/im` → "Added global MCP server 'swiggy-instamart'"; transport stdio, confirmed via `codex mcp get`
- OAuth result: succeeded. Standalone `npx mcp-remote` run opened
  `https://mcp.swiggy.com/auth/authorize?...` in the default browser; since the
  browser already held an active Swiggy session, authorization completed
  without a fresh OTP prompt. Token cached by `mcp-remote`'s local auth store;
  reused successfully by a subsequent `codex exec` call to `get_addresses`.
- Authentication latency: near-instant (pre-existing browser session, no manual
  OTP step observed this run)
- Deviations/interventions: OAuth consent was satisfied by an already-logged-in
  browser session rather than a fresh interactive login — **unconfirmed which
  Swiggy account this is**; see blocker below.

### Blocker — address precondition failed (resolved)

First live call to `get_addresses` returned `{"addresses": [], "total": 0}`.
Operator confirmed the address had not been saved yet; after saving one, a
repeat `get_addresses` call returned 1 saved address under the expected
account holder's name — confirms this is the intended operator account.
Blocker cleared; proceeding into Part B.

## Live tool schema snapshot

| Tool | Required inputs | Read/write effect | Declared output | Observed notes |
| --- | --- | --- | --- | --- |
| `get_addresses` | none | read | `addresses[]`, pagination | live: 2nd call returned 1 saved address |
| `search_products` | `addressId`, `query` (optional `offset`) | read | `success`, `data.products[].variations[]` w/ `spinId`, `price.offerPrice`, `isInStockAndAvailable` | live: query "milk" → 10+ variations, all in stock |
| `your_go_to_items` | | | | |
| `update_cart` | | | | |
| `get_cart` | | | | |
| `clear_cart` | | | | |
| `checkout` | | **Do not invoke** | | |
| `get_orders` | | | | |
| `track_order` | | | | |
| `report_error` | | | | |

## Address and serviceability

- Address label: Home
- Redacted address ID: d9mi8vc1***itji8n3pg
- Serviceable: yes
- Evidence: `get_addresses` (2nd call, after operator saved the address) →
  1 saved address, `addressCategory: "Home"`, account holder name matched
  the expected operator; confirmed serviceable by `search_products` returning
  in-stock, purchasable results for that address

## Product search

- Exact query: `milk`
- Search latency: not separately timed (bundled in agent turn)
- Product name: Amul Gold Milk 1 Ltr
- Pack/variant: 1 ltr
- Price: ₹72 (MRP = offer price, no discount)
- Availability: in stock, purchasable
- Product/variant ID: skuId C6NRLWW5PA
- `spinId`: S8PF9T8YLG
- Alternatives/ads returned: yes — 10+ other milk products/brands (Country
  Delight, Amul Taaza, Maiva Life almond milk variants), all in stock
- Tool result: success
- Error and retry guidance, if any: none, first call succeeded
- Evidence: `search_products(addressId=..., query="milk")` →
  `success: true`, product list as above

## MCP cart

- Update result: success — `update_cart(spinId=S8PF9T8YLG, quantity=2)` →
  "Cart updated successfully with 1 items."
- Redacted cart ID: e6102fa4-***-a36f
- Items and quantities: Amul Gold Milk 1 Ltr × 2
- Subtotal: ₹144.00 (Item Total)
- Taxes: none itemized separately
- Delivery fee: FREE (Delivery Partner Fee)
- Handling/platform fees: ₹3.00
- Discounts: none (MRP = offer price, no cart-level discount)
- Final total: ₹147 (To Pay)
- Currency: INR
- ETA: not returned by this tool (not shown in `get_cart` response)
- Available payment methods: not fetched yet — deferred to Part C per
  DIRECTIONS.md (browser-only payment surface inspection); tool response
  message hints at a separate `get_payment_options` MCP tool not in the
  doc's original tool list — noted, not called
- Quote timestamp: not separately recorded (bundled in agent turn); both
  `update_cart` and `get_cart` returned identical totals, no drift between
  calls
- Evidence: `update_cart` then `get_cart` on the same `addressId`, both
  returned `cartTotalAmount: "₹147"`, identical `cartId`, identical single
  line item

**Note — PII exposure in raw tool output:** both `update_cart` and `get_cart`
embedded the full account holder name, full mobile number, full street
address, and precise lat/lng coordinates directly in `selectedAddressDetails`
— not just the address ID. Redacted before writing to this record per Rule 8;
flagging this as a real characteristic of the live API surface: any bot
wrapping these tools must scrub this field before logging, not just avoid
requesting it.

## Browser cart synchronization

| Field | MCP value | Browser value | Exact match? |
| --- | --- | --- | --- |
| Address label | Home | Home | yes |
| Product | Amul Gold Milk 1 Ltr | Amul Gold Milk 1 Ltr | yes |
| Variant | 1 ltr | 1 ltr | yes |
| Quantity | 2 | 2 | yes |
| Subtotal | ₹144 | ₹144 | yes |
| Delivery fee | FREE | FREE | yes |
| Other fees (handling) | ₹3 | ₹3 | yes |
| Discounts | none | none | yes |
| Final total | ₹147 | ₹147 | yes |

- Synchronization result: confirmed
- Redacted evidence: operator manually compared the MCP-reported cart against
  the same account's normal-browser Instamart cart; all fields matched
  exactly, no discrepancies observed. Automated Playwright-MCP comparison was
  attempted first but the tool call was cancelled at an approval prompt;
  operator verified manually instead per the doc's intended browser-only Part
  C design.

## Browser payment surface

- Credit/debit card option present: yes
- New-card form present: yes
- Card-number field present: (to confirm at Part E entry time)
- Expiry field present: (to confirm at Part E entry time)
- CVV field present: (to confirm at Part E entry time)
- Cardholder-name field required: unknown
- Save-card control present: unknown — must confirm and disable before Part E
- Save-card default: unknown — must confirm and disable before Part E
- Gateway/provider: not yet identified
- Does payment entry occur before order creation?: presumed yes (standard
  Swiggy checkout flow) — confirm explicitly before Part E
- What this proves: Checkpoint B condition (browser sees same MCP cart +
  offers new-card entry) is satisfied
- What remains unknown: save-card default state, exact gateway/provider name
- Evidence: operator confirmed via manual browser inspection, stopped short
  of order submission

## Prava session

- Integration surface: hosted SDK/API sandbox (`POST /v1/sessions`)
- Merchant: Swiggy Instamart
- Merchant URL: https://www.swiggy.com/instamart
- Merchant country: IN
- Amount: ₹147.00
- Currency: INR
- Products/fees included: Amul Gold Milk 1 Ltr × 2 (₹144) + Handling fee (₹3)
- Product lines equal total: yes
- Redacted session ID: ses_01KYX6JJ***BFKS0
- Redacted response/request ID: order ord_01KYX6JJ***BFKS1
- Approval URL returned: yes — hosted collection iframe URL
  (`sandbox.collect.prava.space`, session param redacted)
- Creation timestamp: session expires_at 2026-07-31T23:16:30Z (15-minute
  sandbox lifetime, matches documented behavior)
- Session token: issued (JWT bearer credential) — **not recorded here**;
  operator pasted the full API response including this token into chat by
  accident; token self-expires in 15 min from issuance, mitigating exposure

## Prava lifecycle

| Sequence | Exact Prava state | Timestamp | Sensitive fields present but not recorded |
| ---: | --- | --- | --- |
| 1 | session created (pending) | expires_at 2026-07-31T23:16:30Z | session_token issued, not recorded |
| 2 | hosted collection page loaded, cart/order-ref confirmed matching | operator-observed, not separately timed | — |
| 3 | **"Verification Unavailable"** — passkey/secure-verification setup failed before any passkey prompt appeared | operator-observed | — |

- Network token present at ready state: n/a — never reached `awaiting_result`
- Expiry present at ready state: n/a
- Cryptogram present at ready state: n/a
- Credential values recorded anywhere: **no**
- Evidence: hosted page at `sandbox.collect.prava.space` correctly rendered
  merchant "Swiggy Instamart", item "Amul Gold Milk 1 Ltr", order ref
  `#e6102fa4-...-a36f` (matches MCP/browser cart identity), then failed with
  "Verification Unavailable — We're unable to set up secure verification
  right now. Please try again later or contact support." Cancel button
  offered; no card fields, OTP prompt, or passkey prompt were ever shown.

## Pre-submission recheck

- [ ] Merchant matches approval
- [ ] Address label matches
- [ ] Items match
- [ ] Quantities match
- [ ] Currency matches
- [ ] Total matches exactly
- [ ] Card-save option is disabled
- [ ] Credential has not been used previously

## Merchant attempt

- Submission count: **must be 0 or 1**
- Submission timestamp:
- Visible result:
- Classification: DECLINED | FAILED | CANCELLED | PENDING | UNKNOWN | SUCCESS
- Redacted checkout/reference ID:
- Browser error text:
- Swiggy browser order-history result:
- MCP `get_orders` result, if called:
- Successful real order found: yes | no | unknown
- Charge observed: yes | no | unknown
- Evidence:

## Prava result reporting

- Merchant outcome known before report: yes | no
- Reported status:
- Report timestamp:
- Redacted response ID:
- Final exact Prava state:
- Evidence:

## Deviations and manual interventions

1. First Prava sandbox session hit "Verification Unavailable" before any
   passkey/OTP prompt appeared; operator chose to retry with a fresh session
   rather than investigate device passkey support or stop the test.

## Security review

- [ ] Phone number absent
- [ ] OTP absent
- [ ] Complete address and coordinates absent
- [ ] OAuth access/refresh tokens absent
- [ ] Cookies absent
- [ ] API keys absent
- [ ] Passkey data absent
- [ ] Network-token value absent
- [ ] Expiry value absent
- [ ] Cryptogram/CVV absent
- [ ] Card was not saved
- [ ] No sensitive browser or terminal logs retained

## Capability conclusion

| Capability | Confirmed | Rejected | Unknown | Evidence |
| --- | :---: | :---: | :---: | --- |
| MCP configuration | x | | | Live `get_addresses` call |
| OAuth authentication | x | | | Browser OAuth and cached-token reuse |
| Address/serviceability | x | | | Search returned in-stock products |
| Product search | x | | | `milk` returned purchasable variants |
| Cart mutation | x | | | Milk quantity 2 persisted |
| Complete quote | x | | | ₹144 items + ₹3 handling = ₹147 |
| Browser cart synchronization | x | | | Manual exact-field comparison |
| New-card browser form | x | | | Operator observed card option/form |
| Prava session creation | x | | | Matching hosted sandbox page |
| Passkey approval | | | x | Verification failed before prompt |
| Scoped credential readiness | | | x | Never reached `awaiting_result` |
| One merchant submission | | | x | Not attempted |
| Known merchant decline | | | x | Not attempted |
| No successful real order | | | x | Order history was not recorded |
| Prava decline reporting | | | x | Not attempted |
| Prava final failure | | | x | Not attempted |

## Final conclusion

- Verdict: **Inconclusive for end-to-end payment; Observed for Swiggy
  discovery/cart/browser parity and Prava session creation.**
- What this proves: production Instamart MCP OAuth, product search, cart
  mutation, complete ₹147 quote, normal-browser cart parity, new-card option,
  and a matching hosted Prava sandbox session all worked once.
- What this does not prove: card/passkey approval, `awaiting_result`, scoped
  credential readiness, one merchant submission, merchant decline, Prava
  result reporting, or final `failed` state.
- Recommended architecture decision: implement only the observed Instamart
  discovery/cart/quote contract and hosted Prava-session boundary. Keep merchant
  checkout disabled until the verification blocker is cleared.
- Reproduction result: not yet reproduced.
- Follow-up: repeat with a fresh hosted session containing an HTTPS callback URL
  in a physical passkey-capable normal browser; capture only safe browser
  capability booleans and a Prava response ID if it fails again.
- Documents/decisions updated: reviewed for the 1 August 2026 integration.
