# Upgrades

SessionLayer's components release independently, and the protocols between
them are explicitly versioned and negotiated — so an upgrade is a rolling,
per-component operation, never a lockstep fleet event. This guide gives you
the compatibility rules, a recommended rollout order, and the rollback story.

## The compatibility contract

Three contracts connect the components:

| Contract | Current version | Negotiated? |
|---|---|---|
| Control Plane ↔ Gateway gRPC | **1.1** (window: 1.0–1.1) | yes — at connect |
| Agent ↔ Gateway wire protocol | **1.0** | yes — at connect |
| REST API | URI-versioned `/v1` | no — clients select the path |

The platform commits to an **N-1 window**: a component at minor version N
still speaks to peers one minor back. Version resolution picks the highest
common version deterministically; peers with **no** common version fail
closed with a typed rejection — never a silent downgrade, never a guess.
Minor versions are strictly additive; breaking changes require a major bump
and go through deprecate-then-remove across at least one release.

Practically: upgrading the Control Plane does not force a same-day Gateway
or Agent upgrade, and vice versa — but don't let components drift more than
one minor apart, because outside the window they will (correctly) refuse
each other.

Check what's running before you start:

```bash
curl -s https://cp.example.com/v1/version        # CP version + supported protocol range
sessionlayer-agent --version                      # Agent version + wire-protocol range
```

## Recommended rollout order

1. **Control Plane first.** Contract changes are additive and originate
   here, and the database migrations are designed expand/contract (below).
   With multiple instances, roll them one at a time behind the load
   balancer; the first upgraded instance runs the migrations at startup, and
   the not-yet-upgraded instances keep running against the expanded schema.
2. **Gateways, one at a time, with a drain.** Send SIGTERM and let the
   [drain sequence](gateway-runbook.md) finish (readiness flips, presence
   releases, live sessions get the deadline); standby Gateways pick up node
   ownership while each instance cycles. Sessions running on the draining
   Gateway end at the deadline — schedule accordingly; users reconnect
   cheaply via their pinned keys.
3. **Agents last, through the verifier.** Roll `sessionlayer-agent update`
   (which verifies signature + provenance and installs atomically —
   [Supply chain](../security/supply-chain.md)) then restart. An agent
   node's sessions drain up to the Agent's drain deadline on restart; with
   HA, its other control channels keep the node reachable throughout.

Order 1→2→3 keeps every hop inside the N-1 window at every moment and means
each layer's server side is never older than its clients' maximum.

## Database migrations: expand / contract

Migrations run automatically at Control Plane startup (Flyway) and follow
the expand/contract discipline for rolling upgrades: a release's migrations
only *add* (columns, tables, indexes) so the previous app version keeps
working against the new schema; removals ("contract") ship in a later
release, after the fleet has settled. Consequences for you:

- A rolling CP upgrade needs no downtime window for schema changes.
- Rolling **back** the CP binary after its migrations ran is safe within the
  expand phase — the old version runs against the expanded schema.
- Take your normal Postgres backup before upgrading anyway; migrations are
  forward-only.

## Rollback

- **Control Plane / Gateway:** deploy the previous release; the N-1 window
  covers the mixed state in both directions, and Gateway drains make the
  swap graceful.
- **Agent:** the updater's anti-rollback refuses a validly-signed *older*
  release by default — that is an attack defense, not an obstacle. For a
  deliberate rollback, pass `--allow-downgrade` explicitly (audited in your
  change record, please) or pin `--current-version` to the floor you intend.

> **Warning:** never work around a version-negotiation refusal by disabling
> or downgrading verification anywhere in the chain. A `VERSION_REJECT` /
> no-common-version error during an upgrade means two components drifted
> outside the N-1 window — the fix is upgrading the lagging component, and
> the refusal is the platform declining to guess at an untested combination.

## Next

- [Gateway runbook](gateway-runbook.md) — the drain sequence in detail.
- [Supply chain](../security/supply-chain.md) — verified Agent updates.
- [High availability](../admin-guides/high-availability.md) — what keeps
  serving while you roll.
- [Troubleshooting](troubleshooting.md) — if the rollout leaves a symptom
  behind.
