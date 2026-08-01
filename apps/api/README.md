# Max API

Owns the main agent, deterministic mission workflow, persistence, and external
service adapters. Commerce, payment, notification, and robot simulators must be
clearly labeled and replaced only by observed integrations.

The navigation stack and robot-side backend remain owned by the navigation team.

## Blinkit + Prava sandbox workflow

`max_api.blinkit_prava` implements the fail-closed commerce path used by the
agent and robot:

```text
Blinkit structured cart + native Share Cart URL
→ receiving-cart parity check
→ Prava sandbox session
→ local approval redirect
→ redacted polling state
→ optional one-time in-process credential injector
→ confirmed merchant result reporting
```

The localhost API never returns Prava's session token, hosted URL, card token,
expiry, or dynamic CVV. Credential injection is disabled by default and has no
HTTP endpoint; a trusted in-process browser adapter must consume it exactly once.

Run the tests:

```bash
PYTHONPATH=apps/api/src python3 -m unittest discover -s apps/api/tests -v
```

Run the local robot/agent API:

```bash
export MAX_COMMERCE_API_KEY=replace_with_at_least_16_random_characters
export PRAVA_SECRET_KEY=sk_test_replace_me
export PRAVA_SANDBOX_ENABLED=true
PYTHONPATH=apps/api/src python3 -m max_api.web
```

`PRAVA_CREDENTIAL_INJECTION_ENABLED` remains `false` until Prava approval works
in a supported passkey-capable browser and a trusted local injector is attached.
`BLINKIT_PAYMENT_SUBMISSION_ENABLED` independently keeps Blinkit's final
`pay_now` MCP tool disabled unless an operator enables one confirmed attempt.

Robot-facing endpoints:

- `POST /api/blinkit-prava/workflows`
- `POST /api/blinkit-prava/workflows/{id}/imported-cart`
- `POST /api/blinkit-prava/workflows/{id}/prava-session`
- `GET /api/blinkit-prava/workflows/{id}`
- `GET /api/blinkit-prava/workflows/{id}/approve?token=...`
- `POST /api/blinkit-prava/workflows/{id}/poll`
- `POST /api/blinkit-prava/workflows/{id}/revoke`
