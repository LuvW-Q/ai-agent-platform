#!/bin/sh

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_ROOT" || exit 1

is_supported_python() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.implementation.name == "cpython" and (3, 10) <= sys.version_info[:2] <= (3, 14) else 1)' >/dev/null 2>&1
}

PYTHON_COMMAND=""
if command -v python3 >/dev/null 2>&1 && is_supported_python python3; then
    PYTHON_COMMAND=python3
elif command -v python >/dev/null 2>&1 && is_supported_python python; then
    PYTHON_COMMAND=python
fi

if [ -z "$PYTHON_COMMAND" ]; then
    printf '%s\n' "Python was not found. Install CPython 3.10 through 3.14, then open preview.command again."
    PREVIEW_EXIT_CODE=1
else
    "$PYTHON_COMMAND" "$PROJECT_ROOT/scripts/preview.py" "$@"
    PREVIEW_EXIT_CODE=$?
fi

if [ "$PREVIEW_EXIT_CODE" -ne 0 ] && [ -t 0 ]; then
    printf '\n%s' "Local preview failed. Press Enter to close this window."
    read -r _unused
fi

exit "$PREVIEW_EXIT_CODE"
