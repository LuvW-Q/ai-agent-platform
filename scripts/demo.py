"""Run the isolated demo service and verify its core user journey."""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from cryptography.fernet import Fernet


def parse_port(value: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=parse_port, default=18081)
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def ensure_port_is_free(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(
                f"Port {port} is already in use. Stop the existing service or choose another port."
            ) from exc


def wait_until_started(server: uvicorn.Server, server_thread: threading.Thread) -> None:
    deadline = time.monotonic() + 45
    while not server.started:
        if not server_thread.is_alive():
            raise RuntimeError("Demo service stopped before startup completed.")
        if time.monotonic() >= deadline:
            raise RuntimeError("Demo service did not start within 45 seconds.")
        time.sleep(0.1)


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    database_path = (project_root / "demo_run.db").resolve()
    if database_path.parent != project_root:
        raise RuntimeError("Demo database path must stay inside the project root.")
    ensure_port_is_free(args.port)
    database_path.unlink(missing_ok=True)

    admin_username = "demo_admin"
    admin_password = "Demo-" + secrets.token_urlsafe(18)
    base_url = f"http://127.0.0.1:{args.port}"
    os.environ.update(
        {
            "SECRET_KEY": secrets.token_urlsafe(48),
            "APP_SECRET_KEY": Fernet.generate_key().decode("ascii"),
            "SQLITE_URL": "sqlite:///" + database_path.as_posix(),
            "ENABLE_DEMO_SEED": "1",
            "INITIAL_ADMIN_USERNAME": admin_username,
            "INITIAL_ADMIN_PASSWORD": admin_password,
            "INITIAL_ADMIN_EMAIL": "demo-admin@example.local",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(args.port),
            "CORS_ORIGINS": base_url,
            "WORKFLOW_CODE_EXECUTION_ENABLED": "0",
        }
    )
    os.chdir(project_root)
    sys.path.insert(0, str(project_root))

    config = uvicorn.Config(
        "main:app",
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="demo-uvicorn", daemon=True)
    server_thread.start()
    try:
        wait_until_started(server, server_thread)
        smoke_result = subprocess.run(
            [
                sys.executable,
                str(project_root / "scripts" / "demo_smoke.py"),
                "--base-url",
                base_url,
                "--username",
                admin_username,
                "--password",
                admin_password,
            ],
            cwd=project_root,
            env=os.environ.copy(),
            check=False,
        )
        if smoke_result.returncode != 0:
            raise RuntimeError("Core demo smoke test failed.")

        print()
        if args.smoke_only:
            print("Demo smoke test passed; stopping the temporary service.")
            return 0

        print(f"Demo is ready: {base_url}/login")
        print(f"Admin username: {admin_username}")
        print(f"Admin password: {admin_password}")
        print(f"Service PID: {os.getpid()}")
        if not args.no_browser and not webbrowser.open(f"{base_url}/login"):
            print("The browser could not be opened automatically; use the URL shown above.")

        print("Press Ctrl+C to stop the demo service.")
        try:
            while server_thread.is_alive():
                server_thread.join(timeout=0.5)
        except KeyboardInterrupt:
            print("\nStopping the demo service...")
            return 0
        if not server.should_exit:
            raise RuntimeError("Demo service exited unexpectedly.")
        return 0
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
        if server_thread.is_alive():
            server.force_exit = True
            server_thread.join(timeout=5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Demo error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
