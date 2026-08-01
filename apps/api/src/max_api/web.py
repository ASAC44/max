from __future__ import annotations

import hmac
import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .blinkit_prava import (
    BlinkitPravaService,
    PravaClient,
    PravaError,
    ValidationError,
    WorkflowStateError,
)


class CommerceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        service: BlinkitPravaService,
        api_key: str,
    ) -> None:
        if len(api_key) < 16:
            raise ValueError("MAX_COMMERCE_API_KEY must contain at least 16 characters")
        self.service = service
        self.api_key = api_key
        super().__init__(address, CommerceHandler)


class CommerceHandler(BaseHTTPRequestHandler):
    server: CommerceServer

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        parts = parsed.path.strip("/").split("/")
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True, "service": "max-commerce"})
            return
        if len(parts) == 5 and parts[:3] == ["api", "blinkit-prava", "workflows"]:
            workflow_id, action = parts[3], parts[4]
            if action == "approve":
                try:
                    location = self.server.service.approval_redirect(
                        workflow_id, parse_qs(parsed.query).get("token", [""])[0]
                    )
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "workflow not found"})
                    return
                except (ValidationError, WorkflowStateError) as error:
                    self._json(HTTPStatus.CONFLICT, {"error": str(error)})
                    return
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", location)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
        if len(parts) == 4 and parts[:3] == ["api", "blinkit-prava", "workflows"]:
            if not self._authorized():
                return
            try:
                self._json(HTTPStatus.OK, self.server.service.get(parts[3]))
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "workflow not found"})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        parsed = urlsplit(self.path)
        parts = parsed.path.strip("/").split("/")
        try:
            if parts == ["api", "blinkit-prava", "workflows"]:
                result = self.server.service.create_workflow(self._body())
                self._json(HTTPStatus.CREATED, result)
                return
            if len(parts) == 5 and parts[:3] == ["api", "blinkit-prava", "workflows"]:
                workflow_id, action = parts[3], parts[4]
                if action == "imported-cart":
                    result = self.server.service.verify_import(workflow_id, self._body())
                elif action == "prava-session":
                    result = self.server.service.create_prava_session(workflow_id)
                elif action == "poll":
                    result = self.server.service.poll(workflow_id)
                elif action == "revoke":
                    result = self.server.service.revoke(workflow_id)
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                self._json(HTTPStatus.OK, result)
                return
        except KeyError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "workflow not found"})
            return
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        except WorkflowStateError as error:
            self._json(HTTPStatus.CONFLICT, {"error": str(error)})
            return
        except PravaError as error:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": error.code})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.api_key}"
        if hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid API key"})
        return False

    def _body(self) -> object:
        if self.headers.get_content_type() != "application/json":
            raise ValidationError("expected application/json")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as error:
            raise ValidationError("invalid Content-Length") from error
        if not 0 < length <= 65_536:
            raise ValidationError("request body size is invalid")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValidationError("request body is incomplete")
        return json.loads(raw)

    def _json(self, status: HTTPStatus, value: object) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def serve_in_thread(
    service: BlinkitPravaService,
    api_key: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8090,
) -> tuple[CommerceServer, threading.Thread]:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("commerce API may bind only to localhost")
    server = CommerceServer((host, port), service, api_key)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def main() -> None:
    api_key = os.environ.get("MAX_COMMERCE_API_KEY", "")
    secret_key = os.environ.get("PRAVA_SECRET_KEY", "")
    port = int(os.environ.get("MAX_COMMERCE_PORT", "8090"))
    public_base_url = os.environ.get("MAX_COMMERCE_PUBLIC_BASE_URL", f"http://127.0.0.1:{port}")
    service = BlinkitPravaService(
        PravaClient(secret_key),
        public_base_url=public_base_url,
        sandbox_enabled=os.environ.get("PRAVA_SANDBOX_ENABLED", "false").lower() == "true",
        credential_injection_enabled=(
            os.environ.get("PRAVA_CREDENTIAL_INJECTION_ENABLED", "false").lower() == "true"
        ),
    )
    server, _ = serve_in_thread(service, api_key, port=port)
    print(f"Max commerce API: http://127.0.0.1:{server.server_port}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
