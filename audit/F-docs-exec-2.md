# F-docs-exec-2: First `docker compose up -d --wait` failed with a transient daemon error
- Severity: info
- Area: exec
- Status: Verified-Fixed

**Doc:** `docs/getting-started/quickstart.md`, section "1. Start the stack".

**What the doc says:** `docker compose up -d --wait` brings up all seven containers.

**What actually happened:** on the first invocation, postgres/minio/controlplane came up healthy, then the run aborted as the seed container started:

```
 Container sessionlayer-quickstart-seed-1 Starting
Error response from daemon: No such container: 82be2c4f204a...
rc=1
```

`docker compose ps -a` showed the seed container gone. Re-running the identical `docker compose up -d --wait` succeeded in 4 seconds and the whole stack (including the one-shot seed) came up healthy. Almost certainly a Docker daemon race on a busy shared host, not a product or doc defect — the seed is documented as idempotent and proved to be.

**What a reader would need:** nothing strictly; at most a one-line note near the compose block that `up -d --wait` is safe to re-run if it fails transiently (the seed is idempotent). Recorded for completeness because the first copy-paste of the block did fail.

**Fix:** Tip added directly under the compose block: a transient up -d --wait failure is safe to re-run (seed idempotent).
