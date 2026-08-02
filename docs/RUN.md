# Run Max locally

This is the shared setup, start, stop, and troubleshooting guide for the Max
agent API and Mission Control dashboard. Run commands from the repository root
unless a section says otherwise.

## What runs on the machine

- The FastAPI service on `http://127.0.0.1:8000`
- Mission Control on `http://127.0.0.1:5173`
- A separate Chromium profile logged into Swiggy for the final checkout form
- Swiggy Instamart MCP through `mcp-remote`; its OAuth login is cached per OS user
- Optionally, an authenticated dry-run mission bridge on the Raspberry Pi
- Optionally, the owner-only Telegram worker and outbound Pi poller described
  in [TELEGRAM-BACKEND.md](TELEGRAM-BACKEND.md)
- The current credit-guarded AWS deployment is documented in
  [AWS-DEPLOYMENT.md](AWS-DEPLOYMENT.md)
- The single-service cloud/Pi runtime and physical safety gates are documented
  in [UNIFIED-RUNTIME.md](UNIFIED-RUNTIME.md)
- Authenticated real-time keyboard control and its fail-safe operating procedure
  are documented in [REMOTE-TELEOP.md](REMOTE-TELEOP.md)

The development script starts the first two services. Browser login, OAuth,
Prava verification, Pi bridge deployment, and secrets remain manual.

## Requirements

- Git
- Python tooling through [uv](https://docs.astral.sh/uv/)
- Node.js 22 or newer with npm and npx
- Google Chrome or Chromium
- Network access to OpenAI, Swiggy MCP, Swiggy, and Prava

## First setup on a new device

Clone the repository, enter it, and run:

```bash
./scripts/setup.sh
```

This installs the locked API and web dependencies, creates `.env` from
`.env.example` only when `.env` does not already exist, and applies database
migrations. It never overwrites an existing `.env`.

### Configure `.env`

For the real hackathon flow, set:

```env
MAX_AGENT_MODE=openai
MAX_COMMERCE_MODE=swiggy
MAX_PAYMENT_MODE=prava
MAX_PURCHASE_ENABLED=false

OPENAI_API_KEY=your-key
OPENAI_MODEL=the-model-the-team-has-validated
MAX_ADMIN_TOKEN=a-random-secret-at-least-24-characters-long

PRAVA_SECRET_KEY=your-sandbox-key
PRAVA_USER_ID=max-demo-owner
PRAVA_USER_EMAIL=the-owner-email-used-for-the-demo
PRAVA_CALLBACK_URL=

SWIGGY_CDP_URL=http://127.0.0.1:9222
SWIGGY_CARDHOLDER_NAME=the-name-entered-on-the-card-form

MAX_ROBOT_MODE=pi
MAX_ROBOT_URL=http://the-private-pi-address:8081
MAX_ROBOT_TOKEN=a-separate-random-secret-at-least-24-characters-long
MAX_ROBOT_DRY_RUN=true
```

Keep `PRAVA_CALLBACK_URL` empty for local polling. Set it only when you have a
stable public HTTPS URL ending in `/api/payments/prava/complete`.

Never commit `.env`, card details, CVVs, OTPs, Prava credentials, OAuth tokens,
or the dedicated browser profile. Transfer team secrets privately.

### Configure the Pi mission bridge

The bridge is deliberately acknowledgement-only. It persists a versioned
mission command but refuses physical motion. This proves the backend-to-Pi
contract without claiming that unvalidated navigation is safe.

Copy these files to the Pi under the same paths used by the service:

```text
apps/robot/max_robot/bridge.py
  → ~/.local/lib/max_robot_bridge.py

apps/robot/systemd/max-robot-bridge.service
  → ~/.config/systemd/user/max-robot-bridge.service
```

Create `~/.config/max-robot/bridge.env` with mode `0600`:

```env
MAX_ROBOT_TOKEN=the-same-separate-secret-used-by-the-Max-API
MAX_BRIDGE_ALLOWED_CLIENT=the-private-IP-of-the-Max-API-machine
```

Then start it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now max-robot-bridge.service
```

Do not enable the Pi drive service as part of this setup. A successful dry-run
acknowledgement reports `motion_started=false` and leaves the mission at
`READY_TO_DISPATCH`. Physical motion requires a separately validated navigation
contract and is not enabled by this bridge.

For a public backend, prefer the outbound Pi poller to this inbound LAN bridge.
The backend deployment, Telegram webhook, worker, and poller setup are documented
in [TELEGRAM-BACKEND.md](TELEGRAM-BACKEND.md).

### Complete Swiggy MCP OAuth

Run:

```bash
npx --yes mcp-remote https://mcp.swiggy.com/im
```

Complete the browser login and authorization. Once the MCP connection succeeds,
stop the foreground command with `Ctrl+C`. The token is cached for this device
and OS user. Repeat this step if Swiggy later asks for OAuth again.

An `EAI_AGAIN` or `Temporary failure in name resolution` message is a local
DNS/network failure, not a Max authentication failure.

### Start the dedicated Swiggy browser

Linux with Google Chrome Stable:

```bash
google-chrome-stable --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.local/share/max-swiggy-browser"
```

Use `google-chrome` or `chromium` instead if that is the installed executable.
The two options begin with two ordinary ASCII hyphens. Smart dashes copied from
formatted chat will make Chrome treat the option as a website.

In this dedicated window:

1. Sign into the Swiggy account authorized through MCP.
2. Open Instamart.
3. Select a currently serviceable saved address.
4. Confirm products and an ETA appear for that address.
5. Leave the browser open while Max runs.

The address label does not need to be `Home`; labels such as `Work` are valid.
Do not use the regular Chrome profile for remote debugging.

## Start Max

With the dedicated Swiggy browser still open, run in another terminal:

```bash
./scripts/dev.sh
```

The script applies pending migrations and starts the API with reload plus the
Vite dashboard. Open `http://127.0.0.1:5173` in any local browser window; it
does not have to be the dedicated Swiggy window.

Enter the exact `MAX_ADMIN_TOKEN` from `.env` into Mission Control. A complete
request looks like:

```text
Get 1 milk under ₹300 for home(ya fir jis name se tumara address saved h)
```

If required information is missing, Max pauses before commerce and asks for it.
Once a live quote exists, inspect it and continue through the Prava approval.
Copy the one-time verification link without opening it first if verification
must happen on a phone or another passkey-capable device. The dashboard polls
Prava and continues automatically while Mission Control remains open.

After approval, Max verifies the cart and quote, opens Swiggy checkout in the
dedicated browser, fills the scoped card data, disables card saving, and submits
once. Never manually retry an attempt whose outcome is unknown. Use **Close
unresolved mission** to preserve that truth while releasing the local active
mission slot.

## Verify the services

```bash
curl http://127.0.0.1:8000/api/health
curl http://the-private-pi-address:8081/api/v1/health
```

The expected response reports a healthy API. The dashboard should load at
`http://127.0.0.1:5173`.

Repository checks:

```bash
cd apps/api && uv run pytest -q
cd ../web && npm run build
```

## Stop and restart

Press `Ctrl+C` in the terminal running `./scripts/dev.sh`; it stops the API and
dashboard together. Close the dedicated Swiggy browser separately.

For the next session:

1. Pull the latest repository changes.
2. Re-run `./scripts/setup.sh` after dependency or migration changes; it is safe
   to run again.
3. Start the same dedicated Swiggy browser profile.
4. Run `./scripts/dev.sh`.

## Common failures

- **Port 8000 or 5173 is already in use:** stop the older API/dashboard process,
  then rerun `./scripts/dev.sh`.
- **Swiggy MCP connection failed:** confirm network access, then repeat the OAuth
  command and finish authorization under the same OS user.
- **Chrome CDP connection failed:** confirm the dedicated browser is still open
  and visit `http://127.0.0.1:9222/json/version` locally.
- **Prava verification unavailable on Linux:** copy the unused one-time link and
  open it first on a supported passkey device.
- **Quote expired:** create a fresh mission/quote; do not submit stale payment
  credentials.
- **Address unserviceable or store closed:** select another currently available
  address/store or wait. Homepage ETA alone does not guarantee availability at
  the final payment instant.
- **Checkout outcome unknown:** do not retry payment. Close the mission as
  unresolved, inspect Swiggy/Prava independently, and begin a fresh mission only
  after understanding the result.
- **Pi bridge rejects the command:** verify `MAX_ROBOT_TOKEN` matches on both
  machines, `MAX_BRIDGE_ALLOWED_CLIENT` is the Mac's current private address,
  and ambient HTTP proxy settings are not routing private-subnet traffic.
