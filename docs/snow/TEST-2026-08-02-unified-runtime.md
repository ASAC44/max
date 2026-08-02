# Test: unified backend and Pi-agent release

- Date/time and timezone: 2026-08-02, Asia/Kolkata
- Operator: Codex with owner authorization
- Goal/question: Can one backend and one fail-closed Pi service carry the
  complete software workflow without a purchase or physical motion?
- Environment: local automated tests, AWS production deployment, Prava sandbox
- AWS host: Lightsail Ubuntu, Docker Compose, Chrome 151

## Preconditions

- Production checkout automation disabled.
- Pi powered off.
- Robot dry-run boundary enabled.
- No Telegram bot credentials available.
- Swiggy OAuth not yet approved in the deployed browser.

## Expected result

- API and dashboard pass automated verification.
- A mixed-provider rehearsal links quote, payment permission, merchant result,
  staged package, Pi acknowledgement, pickup, item secured, return, and
  completion under one parent/child mission chain.
- No test places an external merchant order or reports motor motion.
- AWS migration and HTTPS deployment remain healthy.
- Prava accepts a sandbox session request without moving money.

## Observed result

- 55 API tests passed.
- 32 robot tests passed, including OpenCV, obstruction, emergency stop,
  idempotency, unified agent, and local control socket cases.
- Vite production build passed.
- Alembic clean-database upgrade reached `0004_robot_agent`.
- The complete mixed-provider rehearsal reached `DRY_RUN_COMPLETED`; every
  lifecycle event recorded `motion_started=false`.
- The exact Pi bundle installed successfully in an isolated Linux container
  filesystem and exposed the `max-agent` entrypoint.
- AWS production database was backed up before migration and reached
  `0004_robot_agent`.
- AWS API, dashboard, Caddy, Xvfb, Chrome, VNC, and noVNC were healthy.
- Public HTTPS health returned the configured OpenAI, Swiggy, Prava, and
  production labels.
- Prava created a ₹1 sandbox authorization session whose approval host was
  `sandbox.collect.prava.space`; the redacted result explicitly reported
  `money_moved=false`.
- A second redacted session smoke ran from the deployed AWS API container,
  proving the deployed sandbox key and network path were accepted without
  moving money.
- Prava sandbox health is now checked by the authenticated readiness endpoint.
- `MAX_PURCHASE_ENABLED=false` was verified on the deployed API: an attempted
  checkout command returned `409` before mission or merchant processing.
- Cancelling an unused Prava payment session now invokes the documented
  revocation endpoint, records confirmed/failed revocation truth, and always
  cancels locally so no worker can use a credential after cancellation.
- Readiness correctly reported:
  - Prava sandbox configured;
  - Chrome CDP connected and loopback-only;
  - Telegram blocked because owner credentials are absent;
  - Swiggy MCP blocked pending owner OAuth;
  - Pi offline and motion disabled.

## Deviations and interventions

- The Mac Docker daemon was unavailable, so the exact Pi package installation
  was validated inside the deployed Linux API container instead.
- An initial remote backup one-liner had a shell-quoting error. It failed before
  touching the database or migration. The API remained on `0003`; it was then
  stopped cleanly, copied to `/opt/max/backups/max-before-0004.db`, migrated,
  and verified at `0004`.
- Docker Compose encountered a stale container rename during the final image
  recreation. The newly created container was renamed to the expected
  `max-api-1`, started, and verified healthy with the correct image and
  migration.

## Conclusion

- Confirmed: software orchestration, persistence, idempotency, one-service Pi
  package, staged lifecycle, AWS deployment, Chrome/VNC boundary, and Prava
  session creation.
- Not confirmed at the original release checkpoint: Prava passkey
  approval/scoped credential, a merchant submit/result, or any physical
  motor/pickup behavior. Telegram and Swiggy activation evidence is recorded
  below.
- A real order remains prohibited without separate exact owner approval.
- Physical autonomy remains prohibited until the odometry, physical e-stop,
  stopping-distance, and supervised-route gates in `UNIFIED-RUNTIME.md` pass.

## Post-deployment activation

After the owner explicitly approved transferring the existing Swiggy OAuth
cache from the deployment Mac, the three endpoint-specific cache files were
copied into the AWS `mcp-auth` Docker volume. The upload checksum matched before
installation. The containing directories are mode 0700 and the files are mode
0600, owned by root. The API and order-status worker see the same private
volume. Temporary credential archives were deleted from the Mac, AWS host, and
API container after installation.

The authenticated, read-only production readiness check then reported:

- `swiggy_mcp.connected=true`;
- `required_tools_present=true`;
- 14 Swiggy MCP tools discovered;
- order-status worker connected with zero failures;
- Pi connected;
- purchases disabled and autonomous motion disabled.

No cart mutation, checkout, order, or payment operation was performed.
Prava remains configured as sandbox (`money_mode=test_only`), so this is not
evidence of a real payment path.

The owner subsequently created `@MaxChintu_bot` and sent `/start` in a private
chat. The deployment:

- bound the numeric owner and chat IDs only after confirming they matched;
- stored the token and a separate random webhook secret in a root-only
  `.env.telegram` file;
- registered the HTTPS webhook with zero pending updates;
- started `max-telegram-worker-1`;
- processed three production updates exactly once with no worker error;
- returned HTTP 401 for an invalid webhook secret;
- rejected a correctly authenticated update from a non-owner account;
- kept `MAX_TELEGRAM_AUTO_CHECKOUT=false` and
  `MAX_PURCHASE_ENABLED=false`.

The Prava client was also updated to support an explicit `sandbox` or
`production` environment. Sandbox requires `sk_test_*` and the sandbox API;
production requires `sk_live_*` and the production API. Prefix mismatches fail
closed, approval URL origins are allowlisted per environment, and the external
checkout kill switch remains independent. The expanded API suite passed 76
tests. Production payment is not yet activated because no `sk_live_*` key or
Prava production approval has been supplied.

After deployment, authenticated readiness returned `status=ready` across
Telegram, Swiggy MCP, the loopback Swiggy browser, Prava sandbox, the
order-status worker, and the connected Pi. `safe_to_purchase=false`,
`purchase_enabled=false`, and `motion_enabled=false` remained in force. A fresh
₹1 deployed Prava session smoke returned the allowlisted
`sandbox.collect.prava.space` approval host and explicitly reported
`money_moved=false`.
