# F-docs-acc-7: idle-timeout end reason documented as `IDLE_TIMEOUT`; the API stores `idle_timeout`
- Severity: low
- Area: accuracy
- Status: Verified-Fixed

## Claim (doc)
- `docs/operations/troubleshooting.md:131`: "an idle timeout (`IDLE_TIMEOUT` — activity-tracked …)" in the context of checking `endReason` via `GET /v1/sessions/{id}`.
- `docs/admin-guides/session-limits.md:90–91`: "an idle session is torn down with reason `IDLE_TIMEOUT`."

## Source evidence
`ControlPlane-API/src/main/java/io/sessionlayer/controlplane/grpc/AuthorizationService.java:142–149`
maps the wire enum to the stored/API-visible vocabulary:
`"expired"`, `"idle_timeout"`, `"locked"`, `"error"`, default `"closed"` —
lowercase snake_case. `SESSION_END_REASON_IDLE_TIMEOUT` is the *proto enum
constant*, not the `endReason` value a reader will see or filter on; an
operator filtering `endReason == "IDLE_TIMEOUT"` matches nothing.

## Suggested correction
Write the API-visible literal `idle_timeout` in both places (and, where
useful, list the full closed vocabulary: `expired`, `idle_timeout`, `locked`,
`error`, `closed`).

**Fix:** idle_timeout (lowercase, the stored/API literal) now used in session-limits.md and troubleshooting.md; troubleshooting also lists the full endReason vocabulary (expired, idle_timeout, locked, error, closed).
