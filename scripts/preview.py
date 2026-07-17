"""Prepare an isolated runtime and start the cross-platform local preview."""

from __future__ import annotations

import argparse
import hashlib
import platform
import subprocess
import sys
from pathlib import Path


MIN_PYTHON = (3, 10)
MAX_PYTHON = (3, 14)
IMPORT_CHECK = (
    "import fastapi, uvicorn, sqlalchemy, pydantic, pydantic_settings, "
    "cryptography, httpx"
)


class PreviewError(RuntimeError):
    """A user-facing preview startup error."""


def parse_port(value: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", "-Port", type=parse_port, default=18081)
    parser.add_argument("--no-browser", "-NoBrowser", action="store_true")
    parser.add_argument("--smoke-only", "-SmokeOnly", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def validate_base_python() -> None:
    current = sys.version_info[:2]
    if sys.implementation.name != "cpython" or not MIN_PYTHON <= current <= MAX_PYTHON:
        raise PreviewError(
            "Local preview requires CPython 3.10 through 3.14; "
            f"current runtime is {platform.python_implementation()} {platform.python_version()}."
        )


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True)


def preview_python_path(environment_path: Path) -> Path:
    if sys.platform == "win32":
        return environment_path / "Scripts" / "python.exe"
    return environment_path / "bin" / "python"


def environment_is_ready(preview_python: Path) -> bool:
    if not preview_python.is_file():
        return False
    expected = sys.version_info[:2]
    check_code = (
        "import sys; "
        f"assert sys.implementation.name == 'cpython' and sys.version_info[:2] == {expected!r}; "
        f"{IMPORT_CHECK}"
    )
    try:
        result = subprocess.run(
            [str(preview_python), "-c", check_code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def create_environment(environment_path: Path, *, clear: bool) -> None:
    print("Preparing the isolated preview environment...", flush=True)
    command = [sys.executable, "-m", "venv"]
    if clear:
        command.append("--clear")
    command.append(str(environment_path))
    try:
        run(command)
    except subprocess.CalledProcessError as exc:
        raise PreviewError("Failed to create the preview environment.") from exc


def install_requirements(preview_python: Path, requirements_path: Path) -> None:
    print(
        "Installing preview dependencies (only needed on the first run or after dependency changes)...",
        flush=True,
    )
    try:
        run(
            [
                str(preview_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--upgrade",
                "-r",
                str(requirements_path),
            ]
        )
        run([str(preview_python), "-m", "pip", "check"])
    except subprocess.CalledProcessError as exc:
        raise PreviewError("Failed to install a consistent set of preview dependencies.") from exc

    if not environment_is_ready(preview_python):
        raise PreviewError("Preview dependencies were installed but cannot be imported.")


def prepare_environment(project_root: Path) -> Path:
    requirements_path = project_root / "requirements.txt"
    environment_path = (project_root / ".preview-venv").resolve()
    if environment_path.parent != project_root:
        raise PreviewError("Preview environment path must stay inside the project root.")

    preview_python = preview_python_path(environment_path)
    requirements_stamp = environment_path / ".requirements.sha256"
    requirements_hash = hashlib.sha256(requirements_path.read_bytes()).hexdigest()

    ready = environment_is_ready(preview_python)
    if not ready:
        create_environment(environment_path, clear=environment_path.exists())

    installed_hash = ""
    if requirements_stamp.is_file():
        try:
            installed_hash = requirements_stamp.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            installed_hash = ""

    if not ready or installed_hash != requirements_hash:
        install_requirements(preview_python, requirements_path)
        requirements_stamp.write_text(requirements_hash + "\n", encoding="ascii")

    return preview_python


def main() -> int:
    args = parse_args()
    validate_base_python()
    project_root = Path(__file__).resolve().parent.parent
    preview_python = prepare_environment(project_root)

    command = [
        str(preview_python),
        str(project_root / "scripts" / "demo.py"),
        "--port",
        str(args.port),
    ]
    if args.no_browser:
        command.append("--no-browser")
    if args.smoke_only:
        command.append("--smoke-only")

    print("Starting local preview...", flush=True)
    try:
        return run(command, check=False).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreviewError as exc:
        print(f"Preview error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
