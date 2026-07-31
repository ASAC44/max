# Test: Swiggy Instamart MCP + Browser + Prava Sandbox

> Copy this file to a dated test record and fill it during the test. Never enter
> phone numbers, OTPs, complete addresses, coordinates, OAuth tokens, cookies,
> API secrets, passkeys, network-token values, expiry values, or cryptograms.

## Test identity

- Date/time and timezone:
- Operator:
- Goal: Validate Swiggy Instamart MCP → browser card checkout → Prava sandbox
  decline → Prava final failure.
- Required decision/gate:
- Environment: mixed — Swiggy production account/cart, Prava sandbox payment
- Hardware/device/browser/network:
- Codex/MCP client version:
- Node version:
- `mcp-remote` version:
- Prava API/SDK version:
- Account class: authenticated Swiggy account; no phone number
- Primary documentation checked:

## Preconditions

- [ ] Saved Swiggy address exists
- [ ] Instamart is serviceable
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

- Redacted MCP configuration result:
- OAuth result:
- Authentication latency:
- Deviations/interventions:

## Live tool schema snapshot

| Tool | Required inputs | Read/write effect | Declared output | Observed notes |
| --- | --- | --- | --- | --- |
| `get_addresses` | | | | |
| `search_products` | | | | |
| `your_go_to_items` | | | | |
| `update_cart` | | | | |
| `get_cart` | | | | |
| `clear_cart` | | | | |
| `checkout` | | **Do not invoke** | | |
| `get_orders` | | | | |
| `track_order` | | | | |
| `report_error` | | | | |

## Address and serviceability

- Address label:
- Redacted address ID:
- Serviceable: yes | no | unknown
- Evidence:

## Product search

- Exact query:
- Search latency:
- Product name:
- Pack/variant:
- Price:
- Availability:
- Product/variant ID:
- `spinId`:
- Alternatives/ads returned:
- Tool result: success | failed | unknown
- Error and retry guidance, if any:
- Evidence:

## MCP cart

- Update result:
- Redacted cart ID:
- Items and quantities:
- Subtotal:
- Taxes:
- Delivery fee:
- Handling/platform fees:
- Discounts:
- Final total:
- Currency:
- ETA:
- Available payment methods:
- Quote timestamp:
- Evidence:

## Browser cart synchronization

| Field | MCP value | Browser value | Exact match? |
| --- | --- | --- | --- |
| Address label | | | |
| Product | | | |
| Variant | | | |
| Quantity | | | |
| Subtotal | | | |
| Taxes | | | |
| Delivery fee | | | |
| Other fees | | | |
| Discounts | | | |
| Final total | | | |

- Synchronization result: confirmed | rejected | inconclusive
- Redacted evidence:

## Browser payment surface

- Credit/debit card option present: yes | no | unknown
- New-card form present: yes | no | unknown
- Card-number field present:
- Expiry field present:
- CVV field present:
- Cardholder-name field required:
- Save-card control present:
- Save-card default:
- Gateway/provider:
- Does payment entry occur before order creation?:
- What this proves:
- What remains unknown:
- Evidence:

## Prava session

- Integration surface: hosted SDK/API sandbox
- Merchant:
- Merchant URL:
- Merchant country:
- Amount:
- Currency:
- Products/fees included:
- Product lines equal total: yes | no
- Redacted session ID:
- Redacted response/request ID:
- Approval URL returned: yes | no
- Creation timestamp:

## Prava lifecycle

| Sequence | Exact Prava state | Timestamp | Sensitive fields present but not recorded |
| ---: | --- | --- | --- |
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |

- Network token present at ready state: yes | no
- Expiry present at ready state: yes | no
- Cryptogram present at ready state: yes | no
- Credential values recorded anywhere: **must be no**
- Evidence:

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

1.

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
| MCP configuration | | | | |
| OAuth authentication | | | | |
| Address/serviceability | | | | |
| Product search | | | | |
| Cart mutation | | | | |
| Complete quote | | | | |
| Browser cart synchronization | | | | |
| New-card browser form | | | | |
| Prava session creation | | | | |
| Passkey approval | | | | |
| Scoped credential readiness | | | | |
| One merchant submission | | | | |
| Known merchant decline | | | | |
| No successful real order | | | | |
| Prava decline reporting | | | | |
| Prava final failure | | | | |

## Final conclusion

- Verdict: Confirmed | Observed | Rejected | Inconclusive
- What this proves:
- What this does not prove:
- Recommended architecture decision:
- Reproduction result:
- Follow-up:
- Documents/decisions updated:
