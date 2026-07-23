# RBAC

SessionLayer has **two separate authorization systems**, and this page covers
both: [data-plane RBAC](../getting-started/concepts.md) decides *who may SSH
where, as which Linux login, with which capabilities*; **platform RBAC**
decides *who may administer SessionLayer itself*. They share no rules, no
roles, and no code — an admin who can edit rules does not thereby get SSH
anywhere, and vice versa.

## Prerequisites

- [ ] An admin credential with `rbac:write` (data-plane rules) or
      `rbac:write` + `user:manage` (platform roles and bindings). The
      examples use a bearer token in `$TOKEN` — see
      [Authentication](authentication.md).
- [ ] Nodes enrolled with meaningful labels ([Nodes](nodes.md)).

## Data-plane rules

A rule combines three selectors and an effect:

```text
identity selector × node-label selector × source-IP condition
    → allow | deny  (+ Linux logins, TTL, capabilities)
```

Create one:

```bash
curl -s https://cp.example.com/v1/rules \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: rule-devs-staging-1" \
  -d '{
    "name": "devs-to-staging",
    "identitySelector": { "groups": ["developers"] },
    "nodeLabelSelector": { "env": { "op": "eq", "value": "staging" } },
    "principals": ["deploy"],
    "ttlSeconds": 28800,
    "capabilities": ["shell", "exec", "sftp"],
    "effect": "allow"
  }'
```

Anyone in the IdP group `developers` may now SSH to any node labeled
`env=staging`, as the Linux user `deploy`, for sessions authorized up to 8
hours, with shell, exec, and SFTP. Invalid config — empty principals, a
non-positive TTL, an unknown capability, a malformed selector — is rejected
with a `422` before anything is stored.

### The identity selector

```json
{ "identities": ["alice@example.com"], "groups": ["developers"], "all": true }
```

A rule matches an identity if it is listed in `identities`, if any of the
identity's IdP groups appears in `groups`, or if `all` is `true`. An absent or
empty identity selector selects **no one** — a grant must name a subject
population, so a half-written rule can never widen access.

### The node-label selector

Each key names a node label; its condition is one of four operators, or an
array of them:

```json
{
  "env":  { "op": "eq",   "value": "prod" },
  "role": [ { "op": "eq", "value": "web" }, { "op": "eq", "value": "api" } ],
  "name": { "op": "glob", "value": "web-*" },
  "tier": { "op": "in",   "values": ["1", "2"] },
  "dc":   { "op": "regex", "value": "eu-(west|central)-[0-9]" }
}
```

- **AND across keys, OR within a key** — the example matches nodes where
  `env=prod` AND (`role=web` OR `role=api`) AND the other keys each match.
- `regex` is anchored RE2 — it must match the *entire* label value, and RE2
  cannot backtrack, so a hostile pattern cannot melt the decision path.
- An **absent** node-label selector matches all nodes; a key the node doesn't
  carry fails that key.

### The source-IP condition

```json
{ "permit_cidrs": ["203.0.113.0/24"], "deny_cidrs": ["203.0.113.66/32"] }
```

Source IP is a **deny-only reducer**: it can suppress a grant that would
otherwise match, never create one, and it is never treated as evidence of
identity. This mirrors the platform-wide stance — the Gateway's global CIDR
gate and per-credential source bindings are also pure reducers.

## How a decision is made

At connect time the Control Plane evaluates the **set** of rules — the
decision is a pure function of that set, so rule order never matters and every
replica answers identically:

1. A matching [lock](locks.md) denies. Full stop — no allow, JIT grant, or
   break-glass beats a lock.
2. Otherwise, **any** matching `deny` rule denies (deny-overrides).
3. Otherwise, a matching `allow` rule allows — and the requested Linux login
   must be within the rule's `principals`.
4. Otherwise: **default deny.** No rule, no access.

The user always sees one generic "access denied by policy", whatever the
reason; the specific matched rule or lock is recorded in the
[decision log](audit.md) — the `authz.decision` events of the audit stream —
for admins and auditors. The allow decision is signed and
handed to the Gateway, which re-checks capability, expiry, and the lock set
locally on every channel open — so a `ControlMaster` connection multiplexing
channels for hours cannot outlive a policy change.

A worked example of deny-overrides:

```bash
curl -s https://cp.example.com/v1/rules \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: rule-deny-contractors-prod-1" \
  -d '{
    "name": "contractors-never-prod",
    "identitySelector": { "groups": ["contractors"] },
    "nodeLabelSelector": { "env": { "op": "eq", "value": "prod" } },
    "principals": ["deploy"],
    "ttlSeconds": 1,
    "effect": "deny"
  }'
```

A contractor who is *also* in `developers` and covered by ten allow rules is
still denied on every `env=prod` node — one matching deny beats all allows,
in any order. Use explicit deny rules for durable policy ("contractors never
touch prod"); use a [lock](locks.md) for "deny *now*, mid-incident" — a lock
tears down live sessions too, and sits above even explicit denies.

## Capabilities

Capabilities gate what a session may do, enforced at the Gateway per channel
open:

| Capability | Granted by default? | Notes |
|---|---|---|
| `shell` | yes (when a rule omits `capabilities`) | interactive shell |
| `exec` | yes (when omitted) | single commands |
| `sftp` | no | SFTP subsystem |
| `scp` | no | legacy `scp` over exec |
| `port_forward_local` | no | local port-forward (`ssh -L`) — see below |
| `port_forward_remote` | no | remote port-forward (`ssh -R`) — see below |
| `agent_forward` | no | **never admitted, by design** — see below |
| `x11` | no | X11 forwarding (`ssh -X`/`-Y`) — see below |

A rule that omits `capabilities` grants `shell` + `exec` only. For `shell`,
`exec`, `sftp`, and `scp`, a withheld capability produces a clear
channel-level refusal, not a generic denial — by then the user is already
authorized, so there is nothing to hide. A refused forward or X11 request
fails plainer — a channel-open or request failure with no reason detail —
so check the rule's capability list before debugging the network
([Troubleshooting](../operations/troubleshooting.md)).

### Granting port forwarding and X11

Add the capabilities to a rule (or a JIT policy) exactly like `sftp`; the
Dashboard's rule and JIT-policy editors list the same eight capabilities as
checkboxes:

```bash
curl -s https://cp.example.com/v1/rules \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: rule-devs-staging-tunnels-1" \
  -d '{
    "name": "devs-staging-tunnels",
    "identitySelector": { "groups": ["developers"] },
    "nodeLabelSelector": { "env": { "op": "eq", "value": "staging" } },
    "principals": ["deploy"],
    "ttlSeconds": 28800,
    "capabilities": ["shell", "exec", "port_forward_local", "port_forward_remote", "x11"],
    "effect": "allow"
  }'
```

The grant is the **only** switch: there is no Gateway config key, environment
variable, or flag that enables or disables forwarding — a Gateway refuses an
ungranted forward no matter how it is deployed. What each capability admits:

- **`port_forward_local`** (`ssh -L`): the **node** dials the target, so a
  forward reaches only what the node itself can reach — the same network
  boundary your node-label rules already assume. A granted `-L` can still
  fail if the node cannot reach the target; the node, not the Gateway,
  makes the connection.
- **`port_forward_remote`** (`ssh -R`): the listener binds on the **node**,
  matching `-R` through a plain bastion. `-R 0:…` lets the node pick a port,
  which is reported back to your client; cancelling the forward unbinds the
  listener.
- **`x11`** (`ssh -X`/`-Y`): the X11 request (protocol, cookie, screen) is
  relayed to the node unchanged; untrusted-mode cookie handling is the node
  `sshd`'s job, exactly as on a plain OpenSSH server.

Two independent controls enforce every grant: the Gateway's per-channel
admission gate, and the inner-leg session certificate, which carries
`permit-port-forwarding` / `permit-X11-forwarding` only when the matching
capability was granted — so the node's own `sshd` refuses an ungranted
forward on its own, even if the Gateway's gate were somehow bypassed
([Trust model](../security/trust-model.md)). The node's `sshd` must also
permit forwarding: `AllowTcpForwarding yes` is OpenSSH's default, but X11
needs `X11Forwarding yes` and `xauth` installed on the node.

Everything else applies unchanged: a [lock](locks.md) tears down a live
forward like any other channel, tunnels count against the per-connection
channel cap, and each tunnel is audited as **metadata only** — one
`port_forward.closed` / `x11_forward.closed` event with capability,
direction, target, byte counts, and duration, never the forwarded bytes
([Audit events](../reference/audit-events.md)).

> **Note:** in ProxyJump mode (`ssh.proxy_jump.enabled`) every `direct-tcpip`
> channel *is* the jump hop, so local forwarding (`-L`) is structurally
> unavailable there regardless of any grant — an architectural property of
> that mode, not a policy refusal. Remote forwarding and X11 are unaffected.

Agent forwarding is a different case entirely:

> **Warning:** the Gateway refuses SSH agent forwarding on every path,
> including ProxyJump, regardless of any `agent_forward` grant — this
> refusal is deliberate and permanent, and the inner-leg certificate never
> carries `permit-agent-forwarding` either. Forwarding your agent to a
> Tier-0 intercepting proxy would hand it signing access to your private
> keys; the platform declines to be trusted that far.

## Platform RBAC

Platform RBAC is a separate system of **roles** (sets of granular
permissions) and **role bindings** (role → user or IdP group, optionally
scoped). It is default-deny, and every admin action is audited.

```bash
curl -s https://cp.example.com/v1/roles \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: role-auditor-1" \
  -d '{
    "name": "auditor",
    "permissions": ["audit:read", "recording:replay"],
    "description": "Read the audit stream and replay recordings"
  }'
```

Bind it to an IdP group, scoped so these auditors only see production:

```bash
# ROLE_ID is the id returned when you created the role (or GET /v1/roles).
curl -s https://cp.example.com/v1/role-bindings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: binding-auditors-prod-1" \
  -d '{
    "roleId": "'$ROLE_ID'",
    "subjectKind": "group",
    "subject": "security-team",
    "scope": { "node_labels": { "env": "prod" } }
  }'
```

The closed permission vocabulary: `rbac:read`, `rbac:write`, `node:enroll`,
`node:quarantine`, `node:remove`, `ca:manage`, `ca:rotate`, `request:approve`,
`recording:replay`, `recording:export`, `recording:delete`, `audit:read`,
`user:manage`, `settings:write`, `lock:read`, `lock:write`,
`breakglass:manage`.

Scoping (by node label, user, or time window) applies to the permissions that
read sensitive history — `recording:replay`, `recording:export`, and
`audit:read` — so you can let a regional team replay only its own nodes'
sessions. Recording access is itself an audited action: who replayed what,
when, appears in the same audit stream as the session it replays.

> **Note:** platform RBAC is additive-only — there are no deny bindings. To
> strip an admin's access, remove or narrow their bindings; to stop an
> identity *right now*, use a [lock](locks.md), which also covers the platform
> surface via session teardown and issuance blocking.

## Updating and deleting

Updates require the resource's current `version` (optimistic concurrency): a
stale version gets a `409` instead of silently overwriting a colleague's
change. Reads (`GET /v1/rules`, `GET /v1/roles`, …) are cursor-paginated;
deletes are idempotent `204`s.

```bash
# RULE_ID is the id returned at create time (or from GET /v1/rules).
# Fetch the current version first.
RULE=$(curl -s https://cp.example.com/v1/rules/$RULE_ID -H "Authorization: Bearer $TOKEN")
VERSION=$(echo "$RULE" | jq .version)

curl -s -X PUT https://cp.example.com/v1/rules/$RULE_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "identitySelector": { "groups": ["developers", "sre"] },
    "nodeLabelSelector": { "env": { "op": "eq", "value": "staging" } },
    "principals": ["deploy"],
    "ttlSeconds": 28800,
    "capabilities": ["shell", "exec", "sftp"],
    "effect": "allow",
    "version": '$VERSION'
  }'
```

## Next

- [Locks](locks.md) — the top-tier deny that beats every rule.
- [JIT access](jit-access.md) — time-boxed grants on top of standing rules.
- [Audit](audit.md) — where every decision and every rule edit lands.
- [API reference](../reference/api.md) — full request/response shapes.
