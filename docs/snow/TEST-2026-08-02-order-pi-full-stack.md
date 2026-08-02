# Test: Swiggy status to unified Pi agent full stack

## Scope

Safe production-like verification with real HTTP and SQLite, mocked Swiggy
status observations, no merchant checkout, no payment movement, and no motor
motion.

## Exercised path

```text
confirmed
→ preparing
→ out for delivery
→ arrived at delivery location
→ backend cursor stream
→ persisted Pi cursor
→ one Swiggy-triggered dry-run job
→ Pi acknowledgement
→ AT_PICKUP
→ ITEM_SECURED
→ RETURNING
→ COMPLETED
```

The test starts the actual FastAPI application on a localhost socket and uses
the actual `RobotBackend`, `UnifiedRobotAgent`, and `BridgeState` clients over
HTTP. It then verifies the persisted mission, job, trigger provenance, robot
node heartbeat, and no-motion lifecycle.

## Regression coverage added

- repeated arrival is idempotent;
- stale states do not move current status backwards;
- terminal states stop future polling;
- one failed order does not block later orders;
- cancellation/failure revokes an outstanding job;
- unsafe ACK replay is rejected even after a valid ACK;
- dashboard and Telegram do not offer a duplicate send action;
- failed Telegram delivery releases its reservation for retry;
- readiness requires connectivity, not configuration alone;
- order-status worker heartbeat is visible and fail-closed.

## Result

- Backend suite: 66 passed.
- Robot suite: 34 passed with socket access, plus 4 subtests.
- Real-HTTP order-to-Pi lifecycle: passed.
- Web production build: passed.
- Actual Swiggy purchase: not attempted.
- Physical motion: disabled.
