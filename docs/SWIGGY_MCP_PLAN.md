# Swiggy MCP integration plan

## Goal

Connect the existing bot to Swiggy's official Food and Instamart MCP servers so
it can search, build a cart, show a final quote, obtain explicit approval, place
an order, and report delivery status.

```text
Bot request
    -> choose Food or Instamart
    -> select saved delivery address
    -> Swiggy search
    -> bot shows options
    -> user selects items
    -> Swiggy cart and live quote
    -> bot shows total, address, and payment method
    -> explicit user approval
    -> Swiggy checkout
    -> bot sends order ID and tracking updates
```

This plan covers only the Swiggy integration and its bot-facing contract. It
does not include Telegram setup, request extraction, Prava, robot dispatch, or
the judge dashboard.

## Implementation

### 1. Connect to Swiggy MCP

- Add one `SwiggyService` used by the bot.
- Connect to the official Streamable HTTP endpoints:
  - Food: `https://mcp.swiggy.com/food`
  - Instamart: `https://mcp.swiggy.com/im`
- Use `https://mcp-staging.swiggy.com/food` and
  `https://mcp-staging.swiggy.com/im` until Swiggy grants production access;
  select the environment with one base-URL setting.
- Use one demo Swiggy account with OAuth 2.1, PKCE, and Dynamic Client
  Registration.
- Keep the access token in memory, never log it, and restart authorization on
  `401` or `419`.
- Keep one persistent session per endpoint and initialize Food and Instamart
  sequentially to avoid unnecessary authentication and rate-limit usage.

### 2. Expose the bot-facing operations

The bot calls these structured operations instead of calling individual MCP
tools directly:

- `get_addresses()`
- `search_food(address_id, query)`
- `get_food_menu(restaurant_id)`
- `search_instamart(address_id, query)`
- `set_cart(service, items)`
- `clear_cart(service)`
- `get_quote(service)`
- `checkout(service, approved_fingerprint)`
- `track_order(service, order_id)`

`get_quote` returns the cart items, discounts, delivery charges, taxes, total,
selected address, available payment methods, and a fingerprint of the approved
cart. Before checkout, re-fetch the cart and reject the purchase if its total or
fingerprint changed.

### 3. Implement the Food flow

Use this MCP sequence:

```text
get_addresses
    -> search_restaurants or search_menu
    -> get_restaurant_menu
    -> update_food_cart
    -> get_food_cart
    -> get_payment_options
    -> place_food_order
    -> check_payment_status and confirm_order when required
    -> track_food_order
```

- Recommend only open restaurants and available menu items.
- Preserve selected variants and add-ons when updating the cart.
- Food carts belong to one restaurant; explicitly flush the cart before
  switching restaurants.
- Reject carts above Swiggy's current Builders Club limit.

### 4. Implement the Instamart flow

Use this MCP sequence:

```text
get_addresses
    -> search_products or your_go_to_items
    -> update_cart
    -> get_cart
    -> get_payment_options
    -> checkout
    -> check_payment_status and confirm_order when required
    -> track_order
```

- Add the chosen product variation using its `spinId`, not the parent product.
- Show similar products only as alternatives.
- Clear the cart before changing the delivery address.
- Handle out-of-stock products, serviceability, minimum-order requirements,
  multi-store results, and partial checkout success.

### 5. Approval, payment, and duplicate protection

- The bot must show the complete cart, final total, delivery address, and only
  the payment methods returned by Swiggy.
- Call a checkout tool only after a fresh, explicit approval from the user.
- Prefer UPI. Return the Swiggy app handoff or QR information to the bot and
  confirm the order only after payment succeeds.
- Offer COD when UPI is unavailable. If UPI fails or is abandoned, obtain new
  confirmation before switching to COD.
- Checkout calls are not assumed to be idempotent. After a timeout or `5xx`,
  query recent orders before retrying so the bot cannot create a duplicate.
- Honour `Retry-After`, use bounded backoff for transient read failures, and
  poll delivery tracking no faster than every 10 seconds.

## Test plan

- Connect to Swiggy's real MCP staging endpoints with the real OAuth flow and a
  dedicated test Swiggy account; do not build or use a fake MCP client.
- Verify the exact Food and Instamart call sequences against Swiggy's live tool
  schemas and seeded staging catalogue.
- Exercise OAuth expiry, rate limiting, upstream errors, and separate carts
  using Swiggy's documented staging scenarios and non-destructive calls.
- Verify stale quotes, changed totals, unavailable items, closed restaurants,
  invalid addresses, minimum orders, and cart-limit rejection.
- Verify UPI success, UPI-to-COD reconfirmation, and duplicate-order
  reconciliation after an uncertain checkout response.
- In Swiggy staging, complete one Food flow and one multi-item Instamart flow,
  then track both staging orders end to end.
- Record the staging demo and submit it through Swiggy Builders Club production
  onboarding before enabling real orders.

## Assumptions

- The current version uses one demo Swiggy account. Per-student delegated OAuth
  is deferred until the bot needs multiple independent Swiggy accounts.
- Tokens are intentionally not persisted; restarting requires login again.
- Automated tests and local demos never place real production orders.
- UPI is used only when the live Swiggy response advertises it; COD is the
  fallback.

References: [Swiggy MCP documentation](https://mcp.swiggy.com/builders/docs/),
[Food tools](https://mcp.swiggy.com/builders/docs/reference/food/), and
[Instamart tools](https://mcp.swiggy.com/builders/docs/reference/instamart/).
