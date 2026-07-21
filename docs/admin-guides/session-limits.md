# Session limits

Session limits bound how much SSH any one identity can hold open: **how many
concurrent sessions**, **how long a session may run**, and **how long it may
sit idle**. This guide shows you how to set cluster-wide defaults and
per-identity policies, and exactly how each knob is enforced.

> **Warning:** out of the box, **all three limits are unlimited** — session
> limits are opt-in. The Control Plane logs a warning at boot while the
> concurrent-session default is unset. Set a cluster default in production:
> an unlimited concurrent cap means one leaked automation credential can open
> sessions without bound.

## Prerequisites

- [ ] `settings:write` to manage policies (reads need `rbac:read`); a bearer
      token in `$TOKEN` ([Authentication](authentication.md)).
- [ ] Access to the Control Plane's deployment configuration for the cluster
      defaults.

## Set cluster defaults (recommended)

Add the defaults to the Control Plane's configuration
(`application.properties` or environment):

```properties
# Concurrent sessions per identity (hard cap, fleet-wide).
sessionlayer.session-limits.default-max-concurrent=3
# Max session duration in seconds (8 hours).
sessionlayer.session-limits.default-max-session-seconds=28800
# Idle timeout in seconds (30 minutes).
sessionlayer.session-limits.default-idle-timeout-seconds=1800
```

Values are reconciled into the stored operator settings at startup and are
authoritative on every boot. Any identity without a more specific policy gets
these.

## Per-identity policies

A policy targets an identity population and overrides one or more knobs —
where several policies match the same identity, the **most restrictive value
wins, per knob**; an absent knob defers to the cluster default:

```bash
curl -s https://cp.example.com/v1/session-limit-policies \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: slp-contractors-1" \
  -d '{
    "name": "contractors-tight",
    "identitySelector": { "groups": ["contractors"] },
    "maxConcurrentSessions": 1,
    "maxSessionSeconds": 3600,
    "idleTimeoutSeconds": 600
  }'
```

The selector uses the same shape as [rule identity selectors](rbac.md)
(`identities` / `groups` / `all`) and must name a non-empty population; a
policy with no knobs set, or a value below 1, is rejected with a `422` —
there is no way to store a policy that limits nothing. Every stored value is
enforced; nothing on this API is decorative.

Updates require the current `version` (`409` on staleness); list is
cursor-paginated; delete is idempotent, and enforcement falls back to the
remaining policies or cluster defaults on the next decision.

## How each knob is enforced

**Concurrent sessions** is a **hard cap** applied inside the authorization
transaction, counted fleet-wide against live session
[leases](../reference/glossary.md) — correct across
multiple Gateways and Control Plane replicas. Under a simultaneous burst of
connection attempts, exactly the cap succeeds; attempt N+1 receives the same
generic "access denied by policy" as any other denial (nothing leaks that a
limit, rather than a rule, said no — the [decision log](audit.md) has the
truth).
Accounting is exact: a lease is released promptly on every teardown path,
including degraded sessions that never recorded, and a session that crashes
without a goodbye self-heals its slot at grant expiry.

**Max session duration** is folded into the decision's grant expiry:
`min(resolved ceiling, the grant's own TTL)`, where the resolved ceiling is
the most restrictive value across the *matching per-identity policies*,
falling back to the cluster default only when no matching policy sets the
knob. A per-identity policy can therefore be **looser** than the cluster
default for its population — the default is a fallback, not a fleet-wide
ceiling. The Gateway's mid-session expiry machinery enforces the result —
run-to-TTL, grace-then-kill, or hard-kill per access model, with a
[lock](locks.md) always overriding.

**Idle timeout** resolves the same way (matching policies first, the cluster
default only as the fallback), is signed into the decision context, and is
applied by the Gateway as the session's inactivity bound **tighten-only
against the Gateway's own static idle ceiling**: the signed value can shorten
that static bound, never extend it. Real activity (client keystrokes reaching
a live channel) resets the clock; an idle session is torn down with end
reason `idle_timeout`.

**Break-glass is exempt from all three.** An emergency session is never
refused because an on-call operator already has three windows open —
[break-glass](break-glass.md) is gated by its own alarms, review, and lock
supremacy instead.

## Watching it work

The relevant meters (see [Metrics](../reference/metrics.md)):

- `sessionlayer.session.limit{outcome=denied}` — concurrency-cap denials.
- `sessionlayer.session.lease.live` — fleet-wide live-lease gauge. Every
  Control Plane instance reports the same fleet-wide number, so dashboards
  must aggregate `max` (or `last`), never `sum`; it reads 0 for the first
  refresh interval after boot.
- `sessionlayer.session.lease.reaped` — leases released by the backstop
  reaper. Nonzero values in steady state deserve a look.
- `sessionlayer.session.lifecycle{rpc,outcome}` — session end/extend RPC
  outcomes.

> **Note:** one documented accepted risk (AR-GW-LEASE-PARTITION): if a
> Gateway loses the Control Plane for longer than ~22.5 minutes (at shipped
> timing defaults) while its sessions run on, the fleet count can
> transiently **under**-count those slots until the sessions really end. No
> over-admission happens during the partition itself — with the Control Plane
> unreachable, new sessions fail closed anyway — and each occurrence is
> visible in the reaper and lifecycle meters. See the
> [trust model](../security/trust-model.md) for the full risk inventory.

## Next

- [Locks](locks.md) — immediate teardown, as opposed to limits' steady-state
  bounds.
- [Session recording](session-recording.md) — what happens during those
  bounded sessions.
- [Metrics](../reference/metrics.md) — the meters above, in full.
- [Production hardening](../security/hardening.md) — the go-live checklist,
  including "set a cluster default cap".
