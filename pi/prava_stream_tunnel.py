#!/usr/bin/env python3
"""Expose the local MediaMTX HLS endpoint through a temporary HTTPS tunnel."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path


TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:8888")
    parser.add_argument(
        "--url-file",
        type=Path,
        default=Path.home() / ".local/state/prava/stream-url",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.url_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.url_file.unlink(missing_ok=True)
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        raise RuntimeError("cloudflared is not installed")

    process = subprocess.Popen(
        [
            cloudflared,
            "tunnel",
            "--no-autoupdate",
            "--url",
            args.origin,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def stop(_signum: int, _frame: object) -> None:
        if process.poll() is None:
            process.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            match = TUNNEL_URL.search(line)
            if not match:
                continue
            temporary = args.url_file.with_suffix(".tmp")
            temporary.write_text(f"{match.group(0)}/\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(args.url_file)
            print(f"Stream tunnel ready: {match.group(0)}", flush=True)
        return process.wait()
    finally:
        args.url_file.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
