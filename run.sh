#!/usr/bin/env bash
#
# run.sh - convenience wrapper around the uuid_toolkit CLI.
#
# Ensures a virtualenv exists, dependencies are installed, and then
# forwards all arguments to `python -m uuid_toolkit.cli`.
#
# Usage:
#   ./run.sh generate --type v4
#   ./run.sh bulk --type v4 --count 1000
#   ./run.sh detect 550e8400-e29b-41d4-a716-446655440000
#   ./run.sh stats

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is not installed or not on PATH." >&2
    exit 1
fi

if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtual environment at ${VENV_DIR} ..."
    python3 -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

if [ -f "${SCRIPT_DIR}/requirements.txt" ]; then
    pip install --quiet --disable-pip-version-check -r "${SCRIPT_DIR}/requirements.txt"
fi

cd "${SCRIPT_DIR}"
python3 -m uuid_toolkit.cli "$@"
