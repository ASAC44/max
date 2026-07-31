# Stripe payment demo

Max creates one test-mode Stripe Checkout Session per normalized order. Stripe
hosts the card form; Max never receives or stores card details.

This component does not call ONDC or Prava. The agent copies product and price
data from ONDC into the request below. Any Prava sandbox credential is entered
only on Stripe's hosted page and must never be sent to this API or written to a
log.

## Install

Activate the same Python environment used to build the ROS workspace, then
install the pinned Stripe SDK and rebuild:

```bash
cd ~/max_ws
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install stripe==15.3.1
source /opt/ros/lyrical/setup.bash
colcon build --symlink-install --packages-select max_robot
source install/setup.bash
```

For Zsh, use the matching `setup.zsh` files instead.

Install the [Stripe CLI](https://docs.stripe.com/stripe-cli) and authenticate:

```bash
stripe login
```

## Configure and start

In terminal 1, start webhook forwarding:

```bash
stripe listen \
  --events payment_intent.payment_failed,payment_intent.succeeded,checkout.session.completed,checkout.session.expired \
  --forward-to http://127.0.0.1:8080/api/payments/stripe-webhook
```

Copy the displayed `whsec_...` signing secret. In terminal 2:

```bash
cd ~/max_ws
source .venv/bin/activate
source /opt/ros/lyrical/setup.bash
source install/setup.bash

export STRIPE_SECRET_KEY="sk_test_replace_me"
export STRIPE_WEBHOOK_SECRET="whsec_replace_me"
export MAX_PAYMENT_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export MAX_PUBLIC_BASE_URL="http://127.0.0.1:8080"
export MAX_PAYMENT_DB="$HOME/.local/state/max/payments.sqlite3"

ros2 run max_robot max-web \
  --host 127.0.0.1 \
  --port 8080 \
  --pin "replace-with-operator-pin" \
  --payments
```

Only Stripe test secret keys are accepted. The server refuses `sk_live_` keys.

## Create a checkout

The agent sends a unique order ID and one to twenty INR line items. Prices are
decimal strings, and the server derives the final total.

```bash
curl --fail-with-body http://127.0.0.1:8080/api/payments/checkout \
  -X POST \
  -H "Authorization: Bearer $MAX_PAYMENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ondc-order-123",
    "currency": "INR",
    "items": [
      {"name": "Demo product", "unit_price": "249.00", "quantity": 1}
    ]
  }'
```

The response contains `payment_id`, `total_amount`, and a Stripe-hosted
`checkout_url`. Repeating the same `order_id` returns the original checkout.

Check the recorded status:

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $MAX_PAYMENT_API_KEY" \
  "http://127.0.0.1:8080/api/payments/pay_replace_me"
```

Possible statuses are `checkout_created`, `payment_failed`, `paid`, and
`expired`.

## Verify the failure path

Open `checkout_url` and use Stripe's generic-decline test card:

```text
Card:   4000 0000 0000 0002
Expiry: any future date
CVC:    any three digits
```

Stripe Checkout must show the decline, the listener must forward
`payment_intent.payment_failed`, and the status endpoint must report
`payment_failed`.

A Prava sandbox credential can then be tried separately on the same hosted
page for the demo. Its visible Stripe rejection is the authoritative evidence:
because it is not a Stripe test card, Stripe may reject it before producing a
PaymentIntent webhook.

## REST contract

- `POST /api/payments/checkout`: Bearer-authenticated checkout creation.
- `GET /api/payments/<payment_id>`: Bearer-authenticated local status.
- `POST /api/payments/stripe-webhook`: Stripe-signature-authenticated events.
- New checkout returns `201`; an idempotent replay returns `200`.
- Invalid input returns `400`, invalid agent authentication returns `401`, and
  Stripe creation failures return `502`.
