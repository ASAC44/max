from __future__ import annotations

import argparse
import time

from .core import LocalizationState, MissionManager, SafetyGate
from .payments import PaymentService
from .web import serve_in_thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Max local control page")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--pin", required=True)
    parser.add_argument(
        "--payments",
        action="store_true",
        help="enable test-mode Stripe checkout endpoints",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="feed fake healthy heartbeats; never use this on the robot",
    )
    args = parser.parse_args()
    gate = SafetyGate()
    if args.demo:
        gate.localization = LocalizationState.TRACKING
        gate.heartbeat_timeout_s = 2
    manager = MissionManager(gate)
    payments = PaymentService.from_environment() if args.payments else None
    server, _ = serve_in_thread(
        manager,
        host=args.host,
        port=args.port,
        operator_pin=args.pin,
        payments=payments,
    )
    print(f"Max control: http://{args.host}:{server.server_port}")
    try:
        while True:
            if args.demo:
                for source in gate.heartbeats:
                    gate.heartbeat(source)
            time.sleep(0.1)
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
