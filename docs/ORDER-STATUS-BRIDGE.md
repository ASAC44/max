# Swiggy order status to Pi bridge

## Contract

The backend owns the authoritative order timeline. The Pi never calls Swiggy
directly and never infers delivery arrival from a chat message.

```text
Swiggy get_orders / track_order
  -> exact order correlation
  -> normalized append-only backend event
  -> authenticated cursor stream to Pi
  -> persisted Pi cursor and latest status
  -> arrival-only dry-run job
  -> Pi acknowledgement and lifecycle events back to backend
```

Normalized states are:

- `ORDER_PLACED`
- `CONFIRMED`
- `PREPARING`
- `READY_FOR_PICKUP`
- `OUT_FOR_DELIVERY`
- `ARRIVED_AT_DELIVERY_LOCATION`
- `DELIVERED`
- `CANCELLED`
- `FAILED`
- `UNKNOWN`

All distinct states are retained as mission events. Unknown states are retained
rather than discarded, but their robot action is always `WAIT`.
Out-of-order provider responses are retained for audit without moving the
current status backwards.

## Arrival gate

Only `ARRIVED_AT_DELIVERY_LOCATION` may:

1. create one staged child fulfilment mission;
2. mark its package-ready source as Swiggy;
3. create one idempotent Pi job with
   `trigger_source=SWIGGY` and
   `trigger_status=ARRIVED_AT_DELIVERY_LOCATION`.

The default job remains fail-closed:

```text
dry_run=true
motion_enabled=false
motion_started=false
```

After physical commissioning, `MAX_ROBOT_DRY_RUN=false` queues a physical job.
Delivery remains blocked until a fresh physical heartbeat reports every
navigation and emergency-stop subsystem healthy.

`DELIVERED` is recorded but does not create a new dispatch. Cancelled, failed,
unknown, and pre-arrival states never queue a robot job. A cancellation or
failure received after arrival revokes a queued or acknowledged robot job and
cancels the staged child before further lifecycle reports are accepted.

## Deployment

`docker-compose.control.yml` runs `order-sync-worker` with the same persistent
MCP OAuth volume as the API. Complete Swiggy OAuth once as the deployed service
user, then confirm readiness shows both `get_orders` and `track_order`.

Required non-secret settings:

```text
MAX_ORDER_SYNC_INTERVAL_SECONDS=5
MAX_ORDER_SYNC_ERROR_INTERVAL_SECONDS=30
MAX_ORDER_SYNC_STATE_FILE=/data/order-sync-worker.json
MAX_ROBOT_MODE=pi_poll
MAX_ROBOT_DRY_RUN=true
MAX_PURCHASE_ENABLED=false
```

The purchase switch remains false until an explicitly authorized real-order
test. The order-status worker does not submit checkout or payment.

The worker writes an atomic heartbeat to the shared data volume after every
cycle. `/api/readiness` treats missing, stale, or failed worker cycles as
blocked, so a running API cannot conceal a stopped tracking worker.

## Verification

The automated end-to-end test sends confirmed, preparing, out-for-delivery,
and arrived snapshots through the backend. It verifies that:

- all four events appear in cursor order;
- no job exists before arrival;
- arrival creates exactly one dry-run job;
- replaying arrival creates no duplicate;
- the Pi persists the status cursor and latest state;
- the job returns Swiggy trigger provenance;
- a failed historical order cannot block a later active order;
- terminal orders stop polling;
- provider cancellation revokes the queued job;
- unsafe acknowledgement replays are rejected;
- no acknowledgement reports motor motion.
