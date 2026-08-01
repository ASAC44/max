# Test Virgin

> Project disposition, 1 August 2026: the experiment remains **Inconclusive** as
> a capability test, but Zepto is **Rejected** as Max's active hackathon path.
> Four opaque search failures plus missing recovery guidance made further retries
> a poor use of the remaining schedule. Historical observations below are
> preserved; do not resume this path without a new explicit decision.

- Date/time: 1 August 2026, started 02:00 IST; MCP configuration recorded at 02:04:21 IST (UTC+05:30)
- Operator: Snow
- Goal: Prava Sandbox and Zepto MCP manual validation
- Required decision/gate: Purchase fails after attempted card payment
- Hardware/device/browser/network: archlynx / Firefox / Wi-Fi via `wlan0` (SSID not recorded)
- Service/package/API: Prava Sandbox | Zepto MCP `https://mcp.zepto.co.in/mcp`
- Account(never include secrets): snow's zepto account
- Primary documentation checked: https://docs.prava.space/api-reference/testing | https://blog.zepto.com/how-zepto-enables-seamless-shopping-through-ai-fcc7d2e43c7b?gi=d1baaa6ce80f

## Preconditions

- MCP client/version: Codex CLI `0.146.0`
- Node version: `v26.4.0`
- `mcp-remote` version: `0.1.38` (`npm` latest resolved on 1 August 2026)
- Operating system: Arch Linux; Linux `7.1.3-zen1-3-zen` x86_64
- Zepto mobile OTP must be completed by the operator outside model context.

## Exact steps

1. Run `codex mcp add zepto -- npx --yes mcp-remote https://mcp.zepto.co.in/mcp`.
2. Run `codex mcp get zepto` and confirm the server is enabled with the expected command and arguments.
3. Restart Codex, then complete Zepto OAuth/mobile OTP in the operator-controlled browser.
4. Re-run the bridge after OAuth and confirm the remote transport and local STDIO proxy start.

## Expected result

- Codex starts `mcp-remote`, opens the Zepto OAuth flow, and exposes the authenticated Zepto tools after operator login.

## Observed result

- Codex saved and reported the `zepto` MCP server as enabled with the expected STDIO command and arguments.
- The first restarted-client attempt closed during `initialize` while an earlier OAuth process still owned callback port `43069`.
- After operator-controlled OAuth completed, `mcp-remote` connected using `StreamableHTTPClientTransport` and reported `Proxy established successfully`.
- An authenticated MCP `tools/list` call returned 23 current tools and their input/output schemas at 02:17:51 IST.

## Evidence

- `codex mcp get zepto` returned `enabled: true`, `command: npx`, and arguments `--yes mcp-remote https://mcp.zepto.co.in/mcp`.
- The post-authentication bridge check reached the Zepto MCP endpoint and established its local STDIO proxy. Cached token contents were not inspected or printed.
- Only MCP initialization and `tools/list` were requested for the schema snapshot; no Zepto tool was invoked.
- `mcp-remote` stored its OAuth session only in its local cache; no token content, OTP, phone number, coordinates, or full address was persisted in the repository evidence.

## Deviations and interventions

- The supplied generic JSON was translated to Codex's equivalent shared `config.toml` entry through `codex mcp add`.
- Codex and the OAuth callback initially shared a 30-second limit; both were increased to 180 seconds. A stale concurrent OAuth process caused one subsequent `initialize` failure and exited before the successful bridge check.

## Current Zepto MCP tool schema

Captured from the authenticated live server on 1 August 2026 at 02:17:51 IST.
“Not declared” means the live tool definition omitted `outputSchema`; the field
must be learned from a later permitted call rather than guessed.

| Exact tool name | Effect | Required parameters | Important declared output fields |
|---|---|---|---|
| `zepto_shop` | Widget entry point; write/destructive annotation; server says not to use from CLI/MCP clients | `intent` (`search`, `order`, `browse`, `cart`, `orders`, or `addresses`) | `intent`, `initialView`; optional `query`, `quantity` |
| `search_products` | Read | `query`; optional `pageNumber=0` | `products[]`, `query`, `totalCount`; product fields include `id`, `productVariantId`, `storeProductId`, `cartProductId`, `name`, `price`, `mrp`, `imageUrl`, `packSize`, `availableQuantity`, `isAd`, `variantId` |
| `search_multiple_products` | Read | `queries[]`; optional `pageNumber=0` | `sections[]`, `totalSections`; each section has `query`, `products[]`, `totalCount`, with the same product identifiers, price, pack, stock, and ad fields as single search |
| `get_product_details` | Read | `product_variant_id` | `productId`, `productVariantId`, `storeProductId`, `name`, `mrp`, `sellingPrice`, formatted prices, `availableQuantity`, `maxAllowedQuantity`, `isActive`, `isInStock`, ratings, description/detail arrays, seller/manufacturer/origin, return/replace fields, `images`, category, `packSize`, unit and weight |
| `get_location_serviceability` | Read | `latitude`, `longitude` | Not declared |
| `select_store` | Write session context | `storeId`; optional `latitude`, `longitude` | Not declared |
| `list_saved_addresses` | Read | None | Not declared |
| `select_saved_address` | Write session context | `addressId` | Not declared |
| `add_saved_address` | Write account data | `type`, `name`, `flatDetails`, `buildingName`, `latitude`, `longitude`, `formattedAddress`, `shortAddress`; optional `landmark`, contact, floor and building type fields | Not declared |
| `update_drop_zone` | Write address delivery context | `dropZoneSlot`; `addressId` is optional in schema even though its description says it must be valid | Not declared |
| `get_user_details` | Read private profile | None | No output schema; description names profile name, email, phone, referral code, account status and user type |
| `update_user_name` | Write account data | `fullName` | Not declared |
| `view_cart` | Read | None | No output schema; description names cart items with `productVariantId`, `storeProductId`, and `quantity` |
| `update_cart` | Write/destructive cart mutation | `deviceId`, `cartItems[]`; each item requires `productVariantId`, `storeProductId`, `quantity`; optional `replaceCart=false` | No output schema; description says updated cart items are returned |
| `get_payment_methods` | Read | None | No output schema; description promises COD and online options with availability status |
| `create_order` | Write; COD preview/order | None; optional `confirmOrder`, `riderTip=0`, `userAddressId`, `useZeptoCash=false` | Not declared |
| `create_online_payment_order` | Write; online-payment preview/order | None; optional `confirmOrder`, `riderTip=0`, `userAddressId`, `useZeptoCash=false` | No output schema; description says a successful order response supplies an `orderId` for `check_payment_status` |
| `create_wallet_order` | Write; Zepto Cash preview/order | None; optional `confirmOrder`, `riderTip=0`, `userAddressId` | Not declared |
| `create_upi_reserve_pay_order` | Write; UPI Reserve Pay preview/order | None; optional `confirmOrder`, `riderTip=0`, `userAddressId`, `useZeptoCash=false` | No output schema; description says a successful order response supplies an `orderId` for `check_payment_status` |
| `check_payment_status` | Read | `orderId`; optional `poll=false` | No output schema; description names terminal states including `SUCCESS`, `FAILED`, and `CANCELLED` |
| `get_order_detail` | Read | `orderId` | No output schema; description names items, pricing and delivery details |
| `list_order_history` | Read private order data | None; optional `limit=10`, `pageNumber=1` | No output schema; description names order IDs, status, items and delivery information |
| `get_past_order_items` | Read private order data | None | No output schema; description names product name, `productVariantId`, and order frequency |

### Capability mapping

| Required capability | Current live tool(s) | Schema status |
|---|---|---|
| Saved addresses | `list_saved_addresses`, `select_saved_address`, `add_saved_address` | Present; outputs not declared |
| Product search | `search_products` | Present with input and output schemas |
| Multiple-product search | `search_multiple_products` | Present with input and output schemas |
| Product/variant details | `get_product_details` | Present with detailed output schema |
| Cart viewing | `view_cart` | Present; outputs only described |
| Cart updates | `update_cart` | Present; exact mutation inputs declared, outputs only described |
| Payment methods | `get_payment_methods` | Present; outputs only described |
| Online-payment preview | `create_online_payment_order` with `confirmOrder=false` or omitted | Present by tool description; response schema absent |
| Order/payment creation | `create_order`, `create_online_payment_order`, `create_wallet_order`, `create_upi_reserve_pay_order` with `confirmOrder=true` | Present; response schemas absent |
| Payment status | `check_payment_status` | Present; request schema declared, response schema absent |
| Order history/detail | `list_order_history`, `get_order_detail` | Present; outputs only described |

The historical name `create_online_payment_order` is still present in the live
schema. The four order tools are annotated as writes but not destructive, so
their annotations are not a sufficient safety gate; `confirmOrder=true` must be
treated as order-affecting regardless.

## Delivery address verification

- Address label: `work`
- Redacted provider ID: `cbd2…01ad`
- Serviceability result: **Serviceable** — Zepto reported delivery to the selected location with a 10-minute ETA.

## Product search: `rio blueberry peach`

- Search text sent: `rio blueberry peach` (no past-order substitution was made)
- Product name: not observed
- Product ID: not observed
- Variant ID: not observed
- Pack size: not observed
- Price: not observed
- Availability: **unknown**, not “unavailable”
- Store/serviceability context: `work`; serviceable; 10-minute ETA; redacted primary store ID `ad2d…37a2`
- Search latency: 67 ms on the first attempt; 60 ms after 25 seconds; 61 ms and 56 ms on later checks
- Observed result: the MCP transport completed, but all four tool calls returned `Error: Failed to search products: API request failed: Too Many Requests` with no structured product payload. Immediately after the fourth failure, `list_saved_addresses` succeeded and still included the selected `work` label. This rules out a general MCP transport/auth timeout and scopes the failure to the search path, but does not distinguish a search-wide limit from an account/store/location-specific search defect. Zepto exposed no upstream HTTP status, headers, or retry window, so this proves only a **reported** rate limit, not that the underlying service actually returned HTTP `429`.
- Documentation check: the official Zepto MCP README contains no rate-limit, `429`, retry, or cooldown guidance. Open issue [#22](https://github.com/zeptonow/mcp/issues/22) requests detailed tool/schema documentation but provides no retry policy.
- Privacy/side effects: Zepto's required `get_past_order_items` read ran before each search; its contents were not printed or retained. No product was substituted and no cart/order mutation ran.

## Cart read

- Tool: `view_cart`
- Context: `work`; serviceable; 10-minute ETA; redacted primary store ID `ad2d…37a2`
- Result: succeeded twice, including once after explicitly establishing the `work` context; cart empty; `totalItems: 0`
- Side effects: none; no cart mutation tool was called
- Diagnostic significance: authenticated account/cart reads work while `search_products` continues to report `Too Many Requests`, further narrowing the fault to the search path

## Integration notes for the final agent

| Layer | Observed behavior | Design consequence |
|---|---|---|
| `mcp-remote` bridge | OAuth blocks the local STDIO `initialize` response; its callback timeout and the MCP client's startup timeout were both 30 seconds by default | Perform account linking as explicit setup, not during an agent turn; production should prefer native remote MCP/OAuth when available |
| `mcp-remote` bridge | Concurrent authentication used a shared callback-port lock; a previous process holding port `43069` caused a later Codex handshake to close | Centralize OAuth per account, prevent concurrent login flows, and recover stale login locks |
| `mcp-remote-client` 0.1.38 | Connected successfully but closed while requesting `tools/list`; the proxy and direct standard MCP requests worked | Do not make this experimental diagnostic CLI a production dependency |
| Zepto tool contract | Many tools omit `outputSchema`, including address, cart, payment-method, order and status tools | Capture redacted live response shapes, validate them at runtime, and normalize only the subset the agent uses |
| Zepto annotations | Order-creation tools are marked as writes but `destructiveHint` is false | Ignore that hint for safety; the application must classify every order/payment tool as high impact |
| Zepto location context | `get_location_serviceability` is marked read-only but reported that it linked the location to the current session | Treat address/store selection as session mutation and isolate it per user and mission |
| Zepto agent instructions | `zepto_shop` says CLI/MCP clients must use the individual tools instead of the widget entry point | Final agent should allow-list individual tools and exclude `zepto_shop` |
| Zepto search instructions | Product search requires `get_past_order_items` first, which reads private order history | Make this privacy-sensitive dependency explicit; do not fetch history outside an authorized shopping flow |
| Zepto prices | Search/detail schemas return numeric prices in paisa while also exposing some formatted price strings | Store and compare integer paisa; format INR only at presentation boundaries |
| Zepto cart | `update_cart` requires `deviceId` plus product/store variant identifiers | Give each mission a stable scoped device/session identifier and retain exact selected variant IDs |
| Zepto preview/order boundary | The same order tools use `confirmOrder=false` or omission for preview and `confirmOrder=true` for placement | Always send `false` explicitly for preview; only deterministic approval code may send `true` after rechecking the quote |
| Zepto payment status | `check_payment_status` defaults to one read; `poll=true` is allowed only when a previous response instructs it | Implement bounded state-machine polling and never blindly retry order creation |
| Zepto serviceability | One read-only serviceability request stalled for several minutes; subsequent identical reads completed in about two seconds | Add bounded timeouts and telemetry; retries are allowed only for proven read-only calls |
| Zepto search errors | The MCP transport succeeded, but `search_products` returned a text-only `Too Many Requests` tool error with no upstream status, headers, structured error, or retry-after value; the official README documents no rate limit or cooldown; this could be a real downstream `429` or a generic/misclassified wrapper error | Classify it as `provider_reported_rate_limit`, not proven HTTP `429` or product unavailability; inspect the tool-error indicator before parsing products, use bounded backoff, and keep retry timing provisional until Zepto documents it |
| Zepto environment | The authenticated endpoint is production-only | No order-affecting call is a test call; require explicit stop conditions and terminal-status recovery |

These are Phase 1 observations, not yet the frozen production contract. Promote
confirmed response shapes and policies into `ARCHITECTURE.md` and `DECISIONS.md`
only after the remaining controlled tests finish.

## Conclusion

- **Inconclusive** until the permitted read-only calls and controlled commerce behavior are observed.
- What this proves: the Zepto MCP bridge is configured, OAuth completed, the transport connects, the current authenticated tool contract exposes every requested capability by name, and the redacted `work` context is serviceable.
- What this does not prove: the selected product exists or is available, successful search behavior after rate limiting clears, quote totals, preview side effects, or payment/order behavior.
- Follow-up: none for the active hackathon plan. Swiggy validation is delegated
  to Mohit under `docs/mohit/`; retain this record as Zepto rejection evidence.
- Documents/decisions updated: `README.md`, `DECISIONS.md`, `PRAVA.md`,
  `ARCHITECTURE.md`, `ROADMAP.md`, `VALIDATION.md`, and `TEST-VIRGIN.md`.
