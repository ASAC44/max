from __future__ import annotations

import hmac
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import InvalidTransition, MissionManager


PAGE = b"""<!doctype html><html lang="en"><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Max control</title>
<style>
body{font:16px system-ui;max-width:42rem;margin:2rem auto;padding:0 1rem}
button,input{font:inherit;padding:.7rem;margin:.25rem}.danger{background:#b00020;color:white}
pre{background:#eee;padding:1rem;overflow:auto}
</style></head><body>
<h1>Max control</h1>
<label>Operator PIN <input id="pin" type="password" inputmode="numeric"></label>
<div>
<button data-action="start">Start</button><button data-action="stop">Stop</button>
<button data-action="resume">Resume</button><button data-action="confirm-pickup">Confirm pickup</button>
<button data-action="cancel">Cancel</button>
<button class="danger" data-action="emergency-stop">Emergency stop</button>
</div>
<pre id="status" aria-live="polite">Loading...</pre>
<script>
const out=document.querySelector("#status"),pin=document.querySelector("#pin");
async function status(){let r=await fetch("/api/status");out.textContent=JSON.stringify(await r.json(),null,2)}
for(const b of document.querySelectorAll("button"))b.onclick=async()=>{
 let headers={}; if(b.dataset.action!=="emergency-stop")headers["X-Operator-Pin"]=pin.value;
 let r=await fetch("/api/mission/"+b.dataset.action,{method:"POST",headers});
 if(!r.ok)alert((await r.json()).error); await status()
};
status();setInterval(status,1000);
</script></body></html>"""


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        manager: MissionManager,
        operator_pin: str,
    ) -> None:
        if len(operator_pin) < 4:
            raise ValueError("operator PIN must contain at least four characters")
        self.manager = manager
        self.operator_pin = operator_pin
        super().__init__(address, ControlHandler)


class ControlHandler(BaseHTTPRequestHandler):
    server: ControlServer

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._json(HTTPStatus.OK, self.server.manager.status())
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        action = self.path.removeprefix("/api/mission/")
        if action not in {
            "start",
            "stop",
            "resume",
            "confirm-pickup",
            "cancel",
            "emergency-stop",
        }:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if action != "emergency-stop" and not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid operator PIN"})
            return
        try:
            self._run(action)
        except InvalidTransition as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        self._json(HTTPStatus.OK, self.server.manager.status())

    def log_message(self, format: str, *args: object) -> None:
        return

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-Operator-Pin", "")
        return hmac.compare_digest(supplied, self.server.operator_pin)

    def _run(self, action: str) -> None:
        manager = self.server.manager
        if action == "start":
            manager.start()
        elif action == "stop":
            manager.pause()
        elif action == "resume":
            manager.resume()
        elif action == "confirm-pickup":
            manager.confirm_pickup()
        elif action == "cancel":
            manager.cancel()
        else:
            manager.emergency_stop()

    def _json(self, status: HTTPStatus, value: object) -> None:
        self._send(
            json.dumps(value, default=str).encode(),
            "application/json",
            status,
        )

    def _send(
        self,
        body: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
        )
        self.end_headers()
        self.wfile.write(body)


def serve_in_thread(
    manager: MissionManager,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    operator_pin: str = "0000",
) -> tuple[ControlServer, threading.Thread]:
    server = ControlServer((host, port), manager, operator_pin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
