# F-docs-acc-4: quickstart prerequisites over-claim beyond what was verified (Compose floor, macOS, first-build time)
- Severity: medium
- Area: accuracy
- Status: Verified-Fixed

## Claim (doc)
`docs/getting-started/quickstart.md`:
- Lines 16–17: "Docker Engine with Docker Compose **v2.24 or newer** (this guide is tested with Docker 29 / Compose v5), on x86_64 or aarch64 **Linux/macOS**."
- Lines 24–27: "On a typical laptop that is **10–30 minutes** of unattended build time."

## Evidence
What was actually verified by the docs effort (writer-flagged soft spot):
Linux only, Compose v5.1.3, and a first build of ~35 min (Control Plane) +
~12 min (Gateway) ≈ 45–50 min on a 2-core machine. Nobody exercised Compose
v2.24 (the floor is an inference from feature usage — `additional_contexts`,
`profiles`, `--wait`), and no macOS run exists. The 10–30 min figure has no
verified data point at its upper bound; the only measured machine took ~47 min.

## Suggested correction
- Prerequisites: "Docker Engine with a current Docker Compose v2 (tested with
  Docker 29 / Compose v5; the stack uses `additional_contexts`, so Compose
  v2.24+ is required), on x86_64 or aarch64 Linux. macOS with Docker Desktop
  is expected to work but is untested."
- Build-time note: "roughly 30–50 minutes on a small (2-core) machine —
  faster with more cores; the 20 minutes of *your* attention starts after it."

**Fix:** prerequisites reworded to the verified envelope (current Compose v2 with the v2.24+ additional_contexts requirement, tested-with wording, Linux verified / macOS expected-but-untested) and the build-time note now states the measured ~30-50 min small-machine figure.
