# AWS deployment

## Current production service

- Lightsail instance: `max-control-prod`
- Region: Mumbai (`ap-south-1`)
- Size: 2 GB RAM, 2 vCPU, 60 GB disk (`small_3_1`, USD 12/month)
- HTTPS dashboard: `https://max.3-110-105-33.sslip.io`
- Public ports: HTTP 80 and HTTPS 443
- SSH: port 22 restricted to the operator Mac's current public IP
- API, dashboard, order-status worker, and Caddy: Docker Compose
- Authenticated single-controller teleoperation relay: API WebSocket endpoints
- Swiggy Chrome, Xvfb, x11vnc, and noVNC: systemd

The hostname contains the current dynamic public IP. If the instance is stopped
and started, retrieve its new IP, update `MAX_PUBLIC_HOST`, `MAX_WEB_ORIGIN`, and
`PRAVA_CALLBACK_URL`, then recreate Caddy and the dashboard.

## Credit-only protection

The `max-credit-guard` Lambda runs hourly. It reads the AWS account-plan credit
balance and deletes the tagged Lightsail backend if the balance reaches USD 30.
Its IAM policy can delete only Max resources tagged:

```text
Project=Max
BillingGuard=credit-only
```

The safety floor is deliberately much larger than one hour of this server's
runtime cost. AWS Budgets is an alerting service rather than a hard billing cap,
so this deletion guard is the enforcement mechanism. Keep the EventBridge rule
enabled and test the Lambda after changing its code or permissions.

Check it without exposing secrets:

```bash
aws freetier get-account-plan-state --region us-east-1
aws lambda invoke \
  --function-name max-credit-guard \
  --region ap-south-1 \
  /tmp/max-credit-guard-response.json
cat /tmp/max-credit-guard-response.json
```

## Administration

The dedicated SSH key is stored on the deployment Mac at:

```text
~/.ssh/max-control-prod
```

Connect:

```bash
ssh -i ~/.ssh/max-control-prod ubuntu@3.110.105.33
```

The Swiggy browser, VNC, noVNC, API application port, and Vite application port
are loopback-only on the server. Open a local noVNC tunnel:

```bash
ssh -N \
  -i ~/.ssh/max-control-prod \
  -L 127.0.0.1:6080:127.0.0.1:6080 \
  ubuntu@3.110.105.33
```

Then visit `http://127.0.0.1:6080/vnc.html` and sign into Swiggy. The Chrome
profile persists across service restarts.

Service checks:

```bash
sudo systemctl status max-xvfb max-chrome max-vnc max-novnc
cd /opt/max
sudo docker compose -f docker-compose.control.yml ps
curl https://max.3-110-105-33.sslip.io/api/health
```

## Safe operating state

Production is currently configured with:

```text
MAX_TELEGRAM_AUTO_CHECKOUT=false
MAX_PURCHASE_ENABLED=false
MAX_ROBOT_MODE=pi_poll
MAX_ROBOT_DRY_RUN=true
MAX_TELEOP_ENABLED=true
PRAVA_ENVIRONMENT=sandbox
```

This permits integration testing but does not authorize an actual Swiggy order
or autonomous robot motion. Remote keyboard input starts with a durable
emergency-stop latch and cannot run until the Pi target agent acknowledges an
operator-requested reset. Telegram is bound to one private owner, with its
webhook secret and bot token stored in the separate root-only
`/opt/max/.env.telegram` file. The Pi agent is installed and connects outbound
to this deployment.

See [REMOTE-TELEOP.md](REMOTE-TELEOP.md) for the manual-control safety contract.
