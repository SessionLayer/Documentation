#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/check_config_drift.py "${1:?usage: check-config-drift.sh <product root with ControlPlane-API/Gateway/Agent>}"
