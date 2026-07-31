# Swiggy Instamart + Prava Validation Directions

## Assignment

Determine whether Max can truthfully use this complete flow:

```text
Swiggy Instamart MCP
→ search product
→ build and review cart
→ same cart appears in normal Swiggy browser checkout
→ browser offers an unsaved credit/debit-card form
→ Prava SDK/API sandbox approval
→ Prava scoped credential submitted once in the browser
→ merchant returns the expected decline
→ DECLINED reported to Prava
```

The result may be **Confirmed**, **Rejected**, or **Inconclusive**. A failed test
is useful evidence. Do not force the test to pass.

Record the work using [`DOCUMENTATION_TEMPLATE.md`](DOCUMENTATION_TEMPLATE.md).

## Primary references

- [Swiggy Instamart MCP reference](https://mcp.swiggy.com/builders/docs/reference/instamart/)
- [Swiggy grocery recipe](https://mcp.swiggy.com/builders/docs/build/recipes/order-groceries/)
- [Swiggy Instamart checkout](https://mcp.swiggy.com/builders/docs/reference/instamart/checkout/)
- [Prava sandbox testing](https://docs.prava.space/api-reference/testing)

## Non-negotiable safety rules

1. **Never call the Swiggy MCP `checkout` tool.** Its documented v1 grocery
   flow is COD and may create a real order.
2. Use Swiggy MCP only for authentication, address selection, search, cart, and
   read-only order inspection. Use the normal Swiggy browser for card entry.
3. Never use a real card or deliberately create a successful production order.
4. Submit a Prava sandbox credential at most once per fresh session.
5. Never retry a timeout or unknown checkout result until Swiggy order history
   proves that no order was created.
6. Disable **save card** before submission.
7. Keep Prava credentials only in process memory or the controlled browser form.
   Never put them in the LLM context, terminal output, screenshots, logs, files,
   browser storage, or Git.
8. Never record phone numbers, OTPs, complete addresses, coordinates, OAuth
   tokens, cookies, passkeys, API secrets, full network tokens, expiry values, or
   cryptograms/CVVs.
9. Stop if merchant, items, quantities, address, currency, or total changes
   after Prava approval.
10. Do not hide manual intervention. Record it in the test document.

## Required setup

- Codex CLI or another MCP-compatible client
- Node.js and `npx`
- Swiggy account with an Indian mobile number
- Saved, Instamart-serviceable address
- Browser logged into the same Swiggy account
- Prava SDK/API sandbox credentials
- Browser/device with passkey support
- Cheap non-restricted products producing a cart around ₹100–₹200
- Private storage for redacted screenshots outside the repository

The official recipe documents a ₹99 minimum. Keep the cart below ₹1,000 and as
small as practical.

## Part A — Connect and inspect Swiggy MCP

### 1. Record the environment

Before making calls, record the date/time and timezone, operator, operating
system, Codex/MCP client version, Node version, `mcp-remote` version, browser,
and network type without SSID or credentials.

### 2. Add the Instamart MCP server

For Codex:

```bash
codex mcp add swiggy-instamart -- \
  npx --yes mcp-remote https://mcp.swiggy.com/im
```

Verify it:

```bash
codex mcp get swiggy-instamart
```

Restart Codex if the new server is not visible.

### 3. Authenticate

Call a harmless tool such as `get_addresses`. Complete mobile/OTP authentication
only in the operator-controlled Swiggy page. Do not paste the OTP into chat.

Record whether OAuth succeeded, the callback class, latency, and any redacted
error.

### 4. Capture the live tool contract

List the authenticated tools and schemas. At minimum, look for:

```text
get_addresses
search_products
your_go_to_items
update_cart
get_cart
clear_cart
checkout
get_orders
track_order
report_error
```

Record exact live names, required parameters, annotations, and declared output
fields. Do not invoke `checkout`.

## Part B — Validate discovery and cart

### 5. Select the delivery address

Call `get_addresses`, let the operator choose, and retain the selected
`addressId` only in the active test. In evidence record only the label and a
redacted ID.

### 6. Search one common product

Search for a low-risk item such as milk, juice, biscuits, or bottled water using
the selected address.

Record the exact query and latency, product name and pack size, price and
availability, product/variant identifier, and `spinId` used for cart mutation.

If search fails, save the redacted error, obey `Retry-After` if supplied, make at
most one controlled retry, use `report_error` if available, and stop.

### 7. Build the cart

Call `update_cart` with the chosen `spinId` and quantity. Keep the complete cart
around ₹100–₹200. Record the selected variant, quantity, update result, and
redacted cart ID.

### 8. Review the MCP cart

Call `get_cart` and record items and quantities, subtotal, taxes, delivery/
handling/platform fees, discounts, exact total and currency, ETA, available
payment methods, cart ID, and timestamp.

Do not call MCP `checkout`.

### Checkpoint A

Continue only if search, cart mutation, and the complete quote all work. Otherwise
stop and classify the Swiggy commerce path as rejected or inconclusive.

## Part C — Validate browser handoff

### 9. Compare the normal browser cart

In a normal browser logged into the same account:

1. Open Swiggy Instamart.
2. Select the same saved address.
3. Open the cart.
4. Compare it with `get_cart`.

Product, variant, quantity, subtotal, fees, discounts, and total must match.
Capture a redacted screenshot without the full address or phone number.

### 10. Inspect payment selection

Proceed only far enough to display payment methods. Do not submit an order.

Record whether the browser exposes credit/debit-card payment, a new-card form,
card number/expiry/CVV fields, any cardholder-name requirement, the payment
gateway/provider, and a save-card control with its default state.

### Checkpoint B

Continue to Prava only if the browser sees the same MCP cart, totals match
exactly, a new unsaved card can be entered, and payment entry happens before
order confirmation.

If the cart does not synchronize or only COD/UPI is available, stop. That is
enough to reject Swiggy + browser + Prava.

## Part D — Validate Prava sandbox

### 11. Record the Prava environment

Record the hosted SDK/API sandbox surface, API/SDK version, browser/device, and
connectivity result. Never record keys.

### 12. Create the exact session

Create a Prava sandbox session bound to:

- merchant: Swiggy Instamart;
- the current verified Swiggy merchant URL;
- merchant country: `IN`;
- currency: `INR`;
- the exact browser cart total; and
- product lines that sum exactly to that total.

Record only redacted Prava session/response IDs, merchant, amount, currency,
product description, approval-URL presence, and timestamp.

### 13. Complete approval

In Prava's hosted surface, complete sandbox card enrollment/selection, sandbox
OTP if required, and passkey approval. Do not record sensitive values.

### 14. Poll the session

Record the exact provider state sequence. At the documented ready state,
currently expected as `awaiting_result`, record only whether the network token,
expiry, and cryptogram fields are present. Never record their values.

## Part E — Attempt browser card payment

### 15. Recheck the immutable purchase

Immediately before card entry, verify that merchant, address label, items,
quantities, currency, and total still match the approved session. Stop on any
difference.

### 16. Enter the credential

In the normal Swiggy browser card form, place the network token in the card-
number field, Prava expiry in the expiry field, and cryptogram in the CVV field.
Disable save-card. The LLM must never receive these values.

### 17. Submit exactly once

Submit once. Expected result: merchant decline of the Prava sandbox credential.

Classify the visible result as `DECLINED`, `FAILED`, `CANCELLED`, `PENDING`,
`UNKNOWN`, or `SUCCESS`.

If `SUCCESS` appears, stop immediately, preserve the order ID, and use the
legitimate Swiggy support/cancellation path. Do not pretend this was expected.

### 18. Inspect merchant state

Capture a redacted result screen. Check normal Swiggy order history and, when
safe, MCP `get_orders`. Confirm whether a real order exists. On timeout or
ambiguity, classify the outcome as `UNKNOWN` and do not retry.

### 19. Report to Prava

Only after a confirmed merchant decline, report `DECLINED` to Prava, poll again,
and confirm its final state is `failed`. Record timestamps and redacted response
IDs.

### 20. Reproduce the terminal result

Repeat only after the first attempt is terminal and proven not to have charged
or created an order. Use a fresh cart/quote, fresh Prava session, and fresh
credential. Never reuse a session or credential.

## Final verdict

The path passes only when all are true:

- MCP OAuth, search, cart, and quote work;
- the browser sees the same cart and total;
- the browser exposes new-card entry;
- Prava sandbox approval and credential readiness work;
- the credential is submitted exactly once;
- the merchant returns a known decline;
- no real order is created;
- `DECLINED` is reported to Prava;
- Prava reaches `failed`; and
- no sensitive data enters evidence or Git.

Use **Rejected** for a reproducible unsupported capability, **Inconclusive** for
an unknown or environmental outcome, and **Confirmed** only for the complete
repeatable chain.
