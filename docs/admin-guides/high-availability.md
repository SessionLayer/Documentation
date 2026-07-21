# High availability

SessionLayer runs in two modes: **single-instance** (the default — one
process, Postgres the only external dependency) and **HA** (multiple Control
Planes and Gateways, opt-in). This guide explains what HA adds, how routing
and failover actually behave, how to drain a Gateway gracefully, and —
honestly — what surviving an instance loss does and does not mean.

If you run single-instance, you can skip the coordination-bus and relay
sections entirely; they only exist in HA mode.

## Prerequisites (HA mode)

- [ ] Postgres in an HA configuration of its own — with **synchronous
      replication for the authorization and audit tables** (a
      [hardening precondition](../security/hardening.md)).
- [ ] A NATS server on a trusted internal network for signaling (below).
- [ ] An L4 load balancer for the Gateways speaking PROXY protocol v2, and an
      L7 balancer for the Control Planes.
- [ ] Agents configured with **two or more Gateway endpoints in distinct
      failure domains** ([Nodes](nodes.md)).

## What lives where

Three mechanisms, deliberately non-overlapping:

- **Postgres — all durable, authoritative state**, including *presence*:
  which Gateway currently owns each agent node's control channel, at what
  address, with a monotonically increasing nonce. Both modes use the same
  rows; only signaling differs.
- **The coordination bus (NATS) — transient signaling only.** Its entire
  vocabulary is "deliver this dial-back request to the Gateway that owns node
  X, and carry that owner's address."
- **Direct Gateway↔Gateway connections — the session bytes.** Established
  per session, to the address carried in the signal. No standing mesh, no
  service discovery.

> **Note:** session bytes **never** traverse the coordination bus — this is a
> tested invariant, not an intention. The bus carries routing signals; the
> bytes flow client → ingress Gateway → owner Gateway → node, directly. The
> ingress Gateway stays the session's owner and recorder, and the client is
> never redirected.

## Ownership, presence, and failover

Several Gateways may hold a live control channel to the same agent node, but
exactly one *owns* it — the one holding the presence row, refreshed by
heartbeat. The others are warm standbys: the log line `presence: standby
(another gateway owns this node)` is normal operation, not an error. When an
owner goes stale (roughly 30 seconds of missed heartbeats), a standby claims
ownership with the next nonce; stale-nonce signals from the deposed owner are
dropped. Ownership and relay routing are keyed by the Gateway's enrolled
**name**, so identity survives restarts.

Routing **fails closed**: an unknown owner, an unreachable peer, or a stale
nonce denies the session (with a bounded timeout so a hung peer can never
hang your SSH handshake), and the next tick self-heals. Deny-wins is
preserved under every partition — a Gateway that cannot confirm the lock feed
refuses what it cannot verify.

## What NFR-1 fleet survival honestly means

Losing one instance:

- **does not** drop sessions running on surviving instances — proven by a
  hard-kill test that keeps passing new bytes on a survivor mid-kill;
- **does** terminate, fail-closed, any session whose bytes physically
  transited the killed instance — there is no live SSH session migration and
  no cross-instance session-state replication, in SessionLayer or anywhere
  else two live SSH crypto states would have to move;
- hands the killed instance's node ownership to standbys within the staleness
  window, and keeps new sessions establishing throughout.

The recovery story for the terminated sessions is deliberate: reconnecting is
cheap (a [pinned key](authentication.md) reconnects silently), lands on a
healthy instance, and re-runs full authorization. Plan for "reconnect in
seconds", not "sessions survive anything".

## Draining a Gateway

On `SIGTERM` the Gateway drains in order: its readiness endpoint flips to 503
while it *keeps accepting* for a short grace period (default 5 s) so your
load balancer deregisters it before it stops listening; then accept loops
stop, presence is released (standbys claim immediately), and agent control
channels close so Agents fail over. Live sessions — its own and the relays it
serves — get a bounded deadline (default 30 s) to finish; anything still live
is torn down through the recorder-finalize path, so no recording is orphaned.

Point the LB health check at the Gateway's `/readyz`, and size probe interval
× unhealthy threshold to fit inside the pre-drain grace. Details and the
config keys are in the [Gateway runbook](../operations/gateway-runbook.md).

## The NATS bus in production

The bundled NATS client is minimal and deliberately dependency-free — it
connects in **plaintext with no authentication**, targeting a trusted
internal network.

> **Warning:** in production, run the coordination bus mutually
> authenticated and encrypted: put a TLS-terminating sidecar or NATS
> leaf-node boundary in front of the broker, with subject authorization so
> only a node's owner may subscribe to its dial-back subject. If the broker
> demands TLS or auth that the built-in client cannot speak, the Gateway
> logs one loud error and stops reconnecting — HA signaling is then down
> and remote-owned sessions fail closed until you fix the sidecar/broker
> pairing. Defense-in-depth behind the bus: owners drop stale-nonce and
> replayed signals, relay tokens are single-use and bound to
> `{node, session, gateway, principal, expiry}`, and relays per node are
> capped.

## Control Plane HA notes

Control Planes are stateless-except-Postgres; run several behind your L7
balancer.

> **Note:** two in-memory keys are per-instance by default, which shows up in
> HA as "a login begun on instance A cannot complete on instance B" and "a
> machine token minted by A fails on B". Set the shared
> `sessionlayer.oidc.state-hmac-key` so OIDC logins complete across
> instances, and either use session affinity for machine-token consumers or
> accept re-auth on failover (machine tokens are short-lived by design).
> This is a documented accepted risk of the current release.

The heavier dependency is Postgres itself: authorization and audit writes are
the platform's source of truth, so its replication mode bounds your data-loss
window. Synchronous replication for those tables is the production
precondition; the CA signer is the other availability peer
([Certificate authorities](certificate-authorities.md)).

## Scaling signals worth watching

A Gateway that owns many nodes heartbeats them in bounded parallel batches;
on a very large fleet or a slow Control Plane the refresh can exceed the
staleness window and ownership flaps (nodes intermittently "unreachable",
fail-closed). The fixes, in preference order: reduce Control Plane heartbeat
latency, add Gateways to shrink per-Gateway ownership, or raise the heartbeat
interval and staleness TTL **in lockstep on both Gateway and Control Plane**.
See the [Gateway runbook](../operations/gateway-runbook.md) for the
diagnosis.

## Next

- [Gateway runbook](../operations/gateway-runbook.md) — drain, presence, and
  relay log lines with actions.
- [Nodes](nodes.md) — configuring Agents with failure-domain-diverse
  channels.
- [Monitoring](../operations/monitoring.md) — what to alert on in an HA
  fleet.
- [Production hardening](../security/hardening.md) — the Postgres and NATS
  preconditions.
