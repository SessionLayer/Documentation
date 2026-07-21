# Locks

A [lock](../getting-started/concepts.md) is SessionLayer's incident-response
primitive: an **un-overridable deny** that takes effect fleet-wide in
seconds. This guide shows you how to lock an identity, group, node, or the
whole fleet, what a lock does to sessions already running, and how the
platform itself uses locks under the hood.

A lock sits *above* every allow mechanism. No standing rule, no approved
[JIT grant](jit-access.md), and no [break-glass](break-glass.md) credential
beats it — and it is independent of certificate lifetimes and CA state, so
locking someone out never requires rotating a CA.

When a lock lands it does three things at once:

1. **Blocks new issuance** — no new session certificates for matching
   subjects.
2. **Prevents session start** — even a still-valid credential is refused at
   authorization.
3. **Tears down matching live sessions** — on every Gateway, mid-connection,
   with each torn-down session's recording finalized and uploaded (a lock
   never costs you the evidence).

## Prerequisites

- [ ] The `lock:write` platform permission (`lock:read` to list); a bearer
      token in `$TOKEN` ([Authentication](authentication.md)).

## Lock an identity

```bash
curl -s https://cp.example.com/v1/locks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "target": { "identities": ["alice@example.com"] },
    "reason": "credential suspected stolen — IR-1234",
    "mode": "strict"
  }'
```

Within the push-propagation window (sub-second to a few seconds per healthy
Gateway), Alice's live sessions are torn down and any reconnect gets the
standard generic "access denied by policy". The reason is operator-facing
only — the locked user is never told a lock exists, because a lock denial
must be indistinguishable from any other denial.

## Lock targets

A target is one or more facets, **OR-matched** — a session or issuance
matching *any* facet is denied:

```json
{
  "identities": ["alice@example.com"],
  "groups": ["contractors"],
  "nodeIds": ["0195b2f0-3c6a-7000-8000-000000000000"],
  "principals": ["root"],
  "nodeLabels": ["env=prod"],
  "all": false
}
```

An empty target is rejected at ingest — a fleet-wide lock is never implicit.
To deny everything (the "stop the world" move), you must say so explicitly:

```bash
curl -s https://cp.example.com/v1/locks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "target": { "all": true },
    "reason": "active incident — freezing all SSH access",
    "mode": "strict",
    "ttlSeconds": 3600
  }'
```

`ttlSeconds` is optional; without it a lock stands until released. Two modes
exist: `strict` (the default — blocks new access *and* tears down live
sessions) and `best_effort` (blocks new access and new channels, but lets
established sessions run). Use `best_effort` when you want to stop the
bleeding without cutting an operator off mid-write.

## Release a lock

```bash
curl -s https://cp.example.com/v1/locks -H "Authorization: Bearer $TOKEN"

# LOCK_ID is the id from the list above.
curl -s -X DELETE https://cp.example.com/v1/locks/$LOCK_ID \
  -H "Authorization: Bearer $TOKEN"
```

Release propagates to every Gateway like creation did. It only stops future
denial — a torn-down session stays torn down; the user reconnects (cheaply,
via their [pinned key](authentication.md)) once policy allows them again.

## Why you can trust a lock under failure

Locks ride an **actively pushed deny-list**: the Control Plane streams the
lock set to every Gateway, which holds it locally and resyncs in full on
every reconnect. The design rule (the platform's safety spine) is
*allow may fail open; deny must fail closed; deny wins*:

- A Gateway whose lock feed is unhealthy stops trusting its cached allows —
  it forces re-validation and refuses what it cannot confirm, including
  break-glass.
- A lock is honored even when the datastore is down and even in break-glass
  mode — there is no degraded state in which a lock stops working.
- Deny-list staleness can only err toward denying too much, never toward
  letting a locked subject through.

## Locks the platform creates for you

Several admin actions are locks in disguise — same push, same supremacy,
same audit trail:

| Action | The lock it creates |
|---|---|
| [Quarantine a node](nodes.md) | a node-scoped lock (`kill` or `drain` for existing sessions) |
| Terminate a session (`POST /v1/sessions/{id}/terminate`) | a short-TTL lock on the session's identity — tears down that identity's live sessions, then auto-expires so they can reconnect under unchanged policy |
| [Revoke a JIT grant](jit-access.md) | a short-TTL identity-scoped teardown lock |
| **Clone detection** | an automatic lock on an Agent or Gateway identity whose credential generation counter forked — two live copies of one credential were detected |

> **Warning:** a clone-detection lock is **never auto-cleared**, deliberately.
> It means either a genuine credential clone (an incident) or a crash in a
> narrow persistence window (rare, fail-closed). Investigate before you
> release it, and re-provision the node rather than unlocking a
> possibly-cloned credential — see the
> [Agent runbook](../operations/agent-runbook.md).

## Next

- [Nodes](nodes.md) — quarantine, the node-shaped lock.
- [Break-glass access](break-glass.md) — what a lock beats, and why that's
  the point.
- [Audit](audit.md) — every lock create/release and every teardown, in one
  stream.
- [Gateway runbook](../operations/gateway-runbook.md) — lock-feed health and
  its failure modes.
