# Test: Unofficial Blinkit MCP

> Sensitive values are intentionally omitted: phone number, OTP, full addresses,
> coordinates, cookies, access tokens, and payment QR contents.

## Test identity

- Date/time and timezone: 2026-08-01, Asia/Kolkata
- Repository: `hereisSwapnil/blinkit-mcp`, version declared as 1.0.2
- Environment: Python 3.12.13, MCP 1.25.0, Playwright 1.57.0, Firefox 144.0.2
- Browser mode: headless Firefox with isolated persistent storage-state file
- Account class: authenticated Blinkit production account
- Order/payment constraint: stop before `pay_now`; no order submission

## Result summary

| Capability | Result | Evidence |
| --- | --- | --- |
| Locked dependency installation | PASS | `uv sync --frozen` installed 32 packages |
| Python compile/import | PASS | `compileall` completed |
| Direct tool registration | PASS | 16 tools listed; manifest exactly matches |
| MCP stdio handshake | PASS | official Python MCP client initialized and listed 16 tools outside the restricted sandbox |
| Phone + OTP login | PASS | UI reached authenticated `Account` state |
| Session persistence | PASS after fix | fresh Firefox context loaded saved auth and showed `Account` |
| Automatic location detection | PASS | Blinkit accepted browser geolocation |
| Saved-address listing | PASS | two saved labels returned; full details not recorded |
| Saved-address selection | PASS | address index 0 selected |
| Product search | PASS | `milk` returned 24 cards; first 10 parsed with IDs/prices |
| Add to cart | PASS | selected product quantity incremented |
| Read cart/quote | PASS after fix | one product row, quantity 1, and correct item/fee/total breakdown |
| Structured cart snapshot | PASS | two items, Home label, three fee categories, and ₹97.00 total parsed live |
| Remove from cart | PASS after fix | quantity decremented and item reported completely removed |
| Share cart | PASS after fix | native Share action generated a two-item `link.blinkit.com` URL; independent GET returned HTTP 200 |
| Checkout navigation | PASS after fix | first click reached payment; repeated proceed is idempotent |
| Payment-method selection | PASS | UPI selected and QR generated; COD unavailable |
| `pay_now` / real order | NOT RUN | intentionally stopped before irreversible action |

## Live observations

- Auth uses a modal on `https://blinkit.com/`; no separate login-page redirect is expected.
- The original login check had a race: absence of visible `Login` was treated as
  success before the profile control rendered. Waiting for the profile control
  and checking its text fixed the false negative on restart.
- Browser storage contained Blinkit auth cookies and local-storage auth state.
- Cart mutations remained scoped to the automation browser/device context and did
  not appear in a separately opened Blinkit app or website session.
- Blinkit's native Share Cart action generated an import link for transferring the
  automation cart to another browser or the mobile app.
- IP geolocation initially selected an unavailable store. Selecting saved address
  index 0 allowed the flow to continue to the payment widget.
- Search returned current live inventory and prices. A low-value milk item was
  used only for cart/checkout testing and removed afterward.
- UPI QR generation succeeded. QR data was neither recorded nor opened, and
  `pay_now` was not invoked.

## Defects found and fixed

1. Removed the `src/server.py` boolean print that contaminated stdio JSON-RPC.
   The final external stdio handshake passes with all 16 tools.
2. `BlinkitAuth.is_logged_in()` was race-prone and could report both false success
   immediately after OTP and false logout immediately after startup.
3. Updated cart modal waits and parsing for Blinkit's current DOM. Final output
   contains one row with the correct quantity and totals; checkout works first try.
4. Fixed the stale CLI auth import, result-index mapping, cart output, and payment call.
5. Replaced nonexistent UPI tools in README/manifest with `select_payment_method`;
   manifest now matches all 16 registered tools.
6. Regenerated `uv.lock` for project 1.0.2 and `python-dotenv`.
7. Added validation for non-positive quantities and negative address indices.
8. Removed the silent Noida fallback; failed detection now requires manual location.
9. Redacted full delivery addresses and payment error payloads from MCP output/logs.
10. Stopped writing UPI QR images to disk and added restrictive session-file modes.
11. Added `share_cart`, which invokes Blinkit's native Share control and returns the
    generated import link to bridge device-local web and app carts.
12. Added `check_cart_snapshot`, which returns the structured, redacted quote used
    for Blinkit/Prava cart parity checks.

## Local test artifacts

- `blinkit-mcp/test/protocol_smoke.py`: real MCP stdio initialization/tool-list check
- `blinkit-mcp/test/login_flow.py`: phone/OTP login and persistence setup
- `blinkit-mcp/test/live_smoke.py`: login/search/add/cart/remove smoke flow
- `blinkit-mcp/test/checkout_smoke.py`: address through payment selection, with cleanup
- `blinkit-mcp/test/validation.py`: invalid quantity/address checks
- `blinkit-mcp/test/share_cart_smoke.py`: live two-item native share-link generation

## Security and side effects

- [x] Phone number omitted from this record
- [x] OTP omitted from this record
- [x] Full saved addresses and coordinates omitted
- [x] Cookies/tokens omitted
- [x] Payment QR omitted
- [x] Shared-cart test used only two low-value items and did not check out
- [x] `pay_now` not invoked
- [x] No real order placed

## Final conclusion

- Verdict: **Working for the tested scope.**
- Proven: authenticated browser session, saved-address selection, live search,
  cart mutation, native share-link generation, checkout navigation, and UPI QR generation.
- Not proven: COD selection (unavailable for the tested cart) or final order submission.
- Recommendation: use this repaired repository as the Blinkit browser-automation
  base, keep live selector regression tests, and retain final payment as an explicit
  user-confirmed action.
