# Nodes

A [node](../getting-started/concepts.md) is a Linux host you reach through
SessionLayer, over its own unmodified `sshd`. This guide shows you how to
enroll one, how SessionLayer addresses it by name, and how to quarantine or
remove it. When you're done, `ssh` sessions to the node flow through the
Gateway: recorded, policy-checked, and auditable.

Every node uses one of two connectivity models, selectable per node; a fleet
can mix both:

| Model | How the Gateway reaches `sshd` | Best for | Node footprint |
|---|---|---|---|
| Agentless | The Gateway dials `node:22` directly | in-VPC nodes the Gateway can reach inbound | none, stock `sshd` plus one trust line |
| Agent | The [Agent](../getting-started/concepts.md) dials *out* to the Gateway; sessions dial back and splice to the node's own `127.0.0.1:22` | NAT'd, firewalled, or outbound-only nodes | the `sessionlayer-agent` binary + a renewable credential |

In both models the node runs its own unmodified `sshd`, and the Gateway
verifies the node's host identity against material you registered at
enrollment. This is never trust-on-first-use.

## Prerequisites

- [ ] A running Control Plane and Gateway ([install guides](../installation/control-plane.md)).
- [ ] An admin credential with the `node:enroll` platform permission (see
      [RBAC](rbac.md)). The examples use a bearer token in `$TOKEN`; sign in
      via OIDC or use a service account's `POST /v1/oauth2/token` grant
      ([Authentication](authentication.md)).
- [ ] On the node: OpenSSH `sshd`, plus the session CA trust line described
      below.

## Prepare the node's sshd (both models)

Every node trusts the platform's session CA, and only the session CA, so the
Gateway can present a per-session certificate for the resolved Linux login.
Export the session CA's public key, in the `TrustedUserCAKeys` line format
`sshd` expects:

```bash
curl -s https://cp.example.com/v1/cas/session/public-key \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r .opensshPublicKey > sessionlayer_session_ca.pub
```

```text
ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBExampleOnlyNotARealKey= sessionlayer-session-ca
```

The call needs `node:enroll`, the same permission the rest of this page uses.
What it returns is public verification material: the CA's public key, never
anything that signs with it. The same endpoint serves `host` and `user`.

Check the response's `fingerprintSha256` against the file that lands on the
node, so a substituted key is caught before any node trusts it:

```bash
ssh-keygen -lf sessionlayer_session_ca.pub
```

```text
256 SHA256:fwIvogAKifM8FC3pF4aW27s8/5Puz7jCVLHpO4kpuv0 sessionlayer-session-ca (ECDSA)
```

Copy the file to each node, then enable verbose logging alongside it:

```text
# /etc/ssh/sshd_config.d/sessionlayer.conf
TrustedUserCAKeys /etc/ssh/sessionlayer_session_ca.pub
LogLevel VERBOSE
```

> **Warning:** re-export and redistribute this file before a session CA
> rotation drains its outgoing key, or sessions to the node stop. The platform
> cannot verify that your fleet's trust distribution finished. See
> [Certificate authorities](certificate-authorities.md).

`LogLevel VERBOSE` makes `sshd` log the certificate key ID
(`session_id + identity`) on every accepted login, which gives you a
node-local, platform-independent second audit trail. See
[Audit](audit.md).

> **Note:** this is additive. Your existing keys, your console access, and
> any other `sshd` auth you run today keep working. SessionLayer never
> disturbs the node's native SSH, so operator-owned recovery paths remain
> valid.

## Enroll an agentless node

Register the node's name, dial address, and a mandatory host-identity
anchor. The anchor is either a host certificate signed by the platform's
[host CA](certificate-authorities.md) (primary) or the node's exact host
public key (fallback). Fetch the host key over a channel you already trust
(your existing config management, or the node's console), for example the
contents of `/etc/ssh/ssh_host_ecdsa_key.pub` on the node.

```bash
curl -s https://cp.example.com/v1/nodes \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "web-01",
    "address": "10.20.0.15:22",
    "labels": { "env": "prod", "role": "web" },
    "pinnedHostKey": "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBExampleOnlyNotARealKey= root@web-01"
  }'
```

> **Warning:** registration without a `hostCertificate` or `pinnedHostKey` is
> rejected, for either connector kind. There is no way to enroll a node "and
> trust whatever key it shows up with later." That would be trust-on-first-use, and a network attacker
> in the Gateway→node path could then impersonate the node. If the node is
> ever re-keyed, update its anchor before the old one stops matching, or
> sessions to it will (correctly) abort. See
> [Repair or rotate a node's host anchor](#repair-or-rotate-a-nodes-host-anchor).

`labels` are what [data-plane rules](rbac.md) and [locks](locks.md) select
on. Label nodes at enrollment time, not later during an incident.

With `sessionlayer.node.enrollment-approval-required=true` on the Control
Plane, the node starts in `pending` and is excluded from targeting until an
admin activates it. It is a deployment property, off by default, not one of
the `/v1/operator-settings` fields.

## Enroll an agent node

Register the node, issue a join token, then start the Agent on the host.
Registration comes first, because it is where the node's host-identity anchor
is set. Skipping it is repairable rather than fatal, but the repair is a
second step you have to notice you need.

### 1. Register the node

An agent node carries no dial address. The Gateway reaches it through the
Agent's outbound channel, so a registration that supplies an address is
rejected.

```bash
curl -s https://cp.example.com/v1/nodes \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "web-02",
    "connectorKind": "agent",
    "labels": { "env": "prod", "role": "web" },
    "pinnedHostKey": "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBExampleOnlyNotARealKey= root@web-02"
  }'
```

`connectorKind` defaults to `agentless`, so a request that omits it registers
a node the Gateway will try to dial.

The host anchor is required here for the same reason an agentless node needs
one. The Gateway runs the same host-identity verification on the inner SSH
leg whichever connector reached the node, and aborts the session when it has
nothing to verify against.

A join is refused if the name is already registered as `agentless`. The two
models are not interchangeable after enrollment: the Control Plane would hand
the Gateway a dial address while the Agent held a control channel nobody
used.

> **Warning:** skipping this step does not fail loudly. An Agent joining a
> name that does not exist creates the node itself, with no anchor, and every
> session to it then aborts at host verification. Such a node reads
> `"health": "unhealthy"`, and `GET /v1/nodes/{nodeId}/host-anchors` returns
> an empty `anchors` list, which is how you tell it apart from a network
> problem. Repair it in place with `PUT` on the same path (below); you do not
> have to abandon the name. Removal would not free it anyway: removal is a
> soft delete, the name stays reserved, and re-registering it returns `409`.

### 2. Issue a join token

The everyday join method is a [join token](../getting-started/concepts.md).
The two alternatives appear in step 3.

```bash
curl -s https://cp.example.com/v1/join-tokens \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "nodeName": "web-02", "ttlSeconds": 3600 }'
```

The response contains the raw token exactly once. Only its hash is stored,
so copy it now for out-of-band delivery to the node. The token is
single-use, short-lived, and scoped to exactly the node name you gave it.
Because issuance is a plain API call, an autoscaler or config-management run
can provision tokens without a human.

### 3. Install and run the Agent

Install the `sessionlayer-agent` binary
([verify the release signature first](../security/supply-chain.md)), then
start it as its dedicated non-root user. `--bootstrap-ca-file` pins the
Control Plane's CA certificate (obtained from your Control Plane install) so
the very first connection is verified too:

```bash
sessionlayer-agent run \
  --node-name web-02 \
  --join-method token \
  --join-token-file /etc/sessionlayer/join-token \
  --cp-endpoint https://cp.example.com:9443 \
  --bootstrap-ca-file /etc/sessionlayer/cp-ca.pem \
  --gateway-endpoint wss://gw.example.com:9444 \
  --gateway-server-name gw-1
```

`--gateway-server-name` is the name the Agent verifies in the Gateway's TLS
certificate, and it is the Gateway's *enrolled* name, not the host it dialed.
The Control Plane issues each Gateway a certificate whose only DNS name is the
name it enrolled under, so this has to match that. It defaults to `gateway`,
which is a working default only for a Gateway enrolled under that name.

> **Warning:** the Agent refuses to start as root. This is a security control,
> not a packaging nicety: node host keys are root-only, so a compromised
> *root* Agent could read the host key and impersonate the node. Run it as a
> dedicated user (the container image runs as uid 65532).

On first contact the Agent exchanges the token for a renewable mTLS identity
with a generation counter, persists it in its data directory, and attaches to
the node you registered in step 1. From then on it renews ahead of expiry on
its own. If a credential
is ever cloned, the generation counter forks and the Control Plane
auto-locks both copies. See [Locks](locks.md).

The other two join methods suit machines that already have an identity:

- `--join-method oidc`: the Agent presents a workload OIDC token (Kubernetes
  service account, CI, cloud identity) via `--join-token`/`--join-token-file`;
  no shared secret to distribute.
- `--join-method mtls`: the Agent presents an operator-PKI certificate via
  `--operator-cert-file` and `--operator-key-file`.

Whatever the bootstrap method, the ongoing credential is always the same
renewable mTLS identity, and revocation is always a lock plus the generation
counter. No join method is a standing bypass.

### 4. Outbound dial-back, and HA

`--gateway-endpoint` is the outbound dial-out; the node needs zero inbound
reachability. Sessions arrive as dial-back requests over that control
channel and are spliced to the node's own `sshd` on loopback. The Agent
refuses any non-loopback splice target at startup, so a compromised Gateway
cannot use it as a network pivot.

For high availability, pass `--gateway-endpoint` two or more times, pointing
at Gateways in distinct failure domains, and set `--min-control-channels 2`:

```bash
sessionlayer-agent run \
  --node-name web-02 \
  --join-method token --join-token-file /etc/sessionlayer/join-token \
  --cp-endpoint https://cp.example.com:9443 \
  --bootstrap-ca-file /etc/sessionlayer/cp-ca.pem \
  --gateway-endpoint wss://gw-a.example.com:9444 --gateway-failure-domain az-1 \
  --gateway-endpoint wss://gw-b.example.com:9444 --gateway-failure-domain az-2 \
  --gateway-server-name gw-a --gateway-server-name gw-b \
  --min-control-channels 2
```

The Agent refuses to boot with two endpoints in one failure domain: that is
not real HA. See [High availability](high-availability.md) for how ownership
and failover work.

## Repair or rotate a node's host anchor

A node's anchor set is replaceable in place, which is what you reach for when
a node is re-keyed and when an Agent auto-created a node with no anchor at
all. Read the current set first (`node:enroll`):

```bash
curl -s https://cp.example.com/v1/nodes/$NODE_ID/host-anchors \
  -H "Authorization: Bearer $TOKEN" | jq '.anchors[] | {source, keyType, fingerprint}'
```

An empty `anchors` list is the diagnosis for a node whose every session
aborts. Replace the set with the anchor the node actually presents now:

```bash
curl -s -X PUT https://cp.example.com/v1/nodes/$NODE_ID/host-anchors \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "pinnedHostKey": "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBExampleOnlyNotARealKey= root@web-01" }'
```

The `PUT` is a whole-set replace in one transaction, so the node is never
briefly anchorless and never briefly still trusting the key you are
retiring. Send at least one of `hostCertificate` or `pinnedHostKey`: an empty
set is a `422`, because a node with no anchor does not fall back to
trust-on-first-use, it stops working. A `removed` node is a `409` — removal
is terminal, and such a host comes back as a fresh registration under a new
name.

Sequence a planned re-key the same way you sequence a CA rotation: write the
new anchor before the node starts presenting it, or sessions abort in the gap.

## How users address a node: name → id

Users always dial a node by its name (`web-01`), carried inside the SSH
connection: `ssh deploy%web-01@gw.example.com`, wildcard DNS, or ProxyJump.
The Gateway extracts the name and the Control Plane resolves it to the
node's id server-side during authorization. An unknown name gets the same
generic "access denied by policy" as any other denial, so probing for node
existence tells an attacker nothing.

The three addressing modes and their client setup are covered in
[SSH access](../user-guide/ssh-access.md).

## Quarantine a node

Quarantine immediately blocks new sessions to the node and, by default,
tears down existing ones. Under the hood it is a [lock](locks.md) on the
node: pushed to every Gateway, fail-closed, un-overridable by any allow, JIT
grant, or break-glass.

```bash
curl -s https://cp.example.com/v1/nodes/$NODE_ID/quarantine \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "reason": "suspected compromise, IR-1234", "existingSessions": "kill" }'
```

`$NODE_ID` is the `id` from `GET /v1/nodes`. Set `"existingSessions":
"drain"` instead to let live sessions finish while refusing new channels.
The reason is for your audit trail only. The SSH user sees the same generic
denial as always.

Release it when the incident is over (never resurrects torn-down sessions):

```bash
curl -s -X DELETE https://cp.example.com/v1/nodes/$NODE_ID/quarantine \
  -H "Authorization: Bearer $TOKEN"
```

## Remove a node

```bash
curl -s -X DELETE https://cp.example.com/v1/nodes/$NODE_ID \
  -H "Authorization: Bearer $TOKEN"
```

Removal deregisters the node (its session and audit history is preserved)
and, for an agent node, revokes the agent credential: the identity is
deactivated and a covering lock is pushed, so a stale copy of the credential
cannot renew and re-joining cannot bypass the revocation. Re-enrolling the
host later means issuing a fresh join token.

Removal is a soft delete: the row survives with `status: removed` so its
history stays attributable, which means the node keeps its name. Registering
that name again returns `409`. Bring the host back under a new node name.

## Node lifecycle at a glance

| Status | Meaning | Targetable? |
|---|---|---|
| `pending` | enrolled, awaiting approval | no |
| `active` | healthy member of the fleet | yes |
| `quarantined` | locked by an admin | no |
| `removed` | deregistered; history kept | no |

Nodes also report `health`, computed per request rather than stored:

| `health` | Means |
|---|---|
| `unhealthy` | The node has no host-identity anchor, so every session to it aborts at host verification. Enrolled but unusable; repair the anchor. This outranks everything below it. |
| `healthy` | An agent node whose Agent holds a control channel to a Gateway, heartbeat fresh. |
| `unreachable` | An agent node a Gateway once held and whose heartbeat has gone stale. |
| `unknown` | An agent node no Gateway has ever claimed, so its Agent has not joined yet. |

> **Note:** an agentless node is **always** `unknown`, and that reports
> nothing wrong. The Control Plane holds no continuous liveness signal for a
> node it dials on demand, and it runs no probe of its own, so `unknown` is
> the only honest answer for the connector model most fleets use. Do not read
> it as a fault, and do not wait for `healthy` on an agentless node: it never
> arrives. `owningGateway` is absent for the same reason.

Users get the generic post-authorization node-offline error whichever of
these applies.

## Next

- [RBAC](rbac.md): write the rules that decide who reaches this node.
- [SSH access](../user-guide/ssh-access.md): how users connect to it.
- [Locks](locks.md): the incident-response primitive behind quarantine.
- [Agent runbook](../operations/agent-runbook.md): exit codes, clone
  detection, and re-provisioning.
