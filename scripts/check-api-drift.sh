#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/check_api_drift.py "${1:?usage: check-api-drift.sh <ControlPlane-API checkout>}"
