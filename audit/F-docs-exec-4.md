# F-docs-exec-4: Audit-trail example surfaces an unexplained bare-UUID actor
- Severity: info
- Area: exec
- Status: Verified-Fixed

**Doc:** `docs/getting-started/quickstart.md`, section "7. See the audit trail".

**What the doc says:** "You get the authorization decision plus the recording lifecycle, correlated by session id." The block projects `{action, actor, outcome}`.

**What actually happened:** the block works, but the output mixes two actor representations with no explanation:

```json
{"action":"recording.finalize","actor":"alice@example.com","outcome":"success"}
{"action":"session.end","actor":"019f86ad-3f36-7358-8422-901969ed2b39","outcome":"success"}
{"action":"authz.decision","actor":"019f86ad-3f36-7358-8422-901969ed2b39","outcome":"success"}
```

A first-time reader has no way to know what `019f86ad-3f36-…` is (presumably the Gateway's platform identity acting on the session). In a section whose point is "one correlated, readable audit stream", an opaque UUID as the actor of the flagship `authz.decision` event undercuts the demo slightly.

**What a reader would need:** one sentence after the block, e.g. "entries acted by the platform itself (the Gateway) carry its component identity as the actor", or have the example project a friendlier field if one exists. Pure polish — nothing is wrong or blocked.

**Fix:** One sentence added after the audit block: platform-acted entries carry the Gateway's enrolled identity as the bare-UUID actor (verified against runtime.gateway_identity).
