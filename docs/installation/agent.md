# Install the Agent

When you finish this page a node with **no inbound reachability** is joined to
the platform: its Agent dials out to your Gateways, holds a renewable mTLS
identity, and splices sessions to the node's own `sshd` on demand.

You only need the Agent for outbound-only nodes (NAT, egress-only firewalls, or
when you want the node-local second audit trail). Nodes the Gateway can reach
directly are better served agentless — nothing to install at all. See
[Nodes](../admin-guides/nodes.md) for choosing per node.

Prerequisites:

- [ ] a join credential from an admin — a join token
      (`POST /v1/join-tokens`), an OIDC workload identity, or an
      operator-PKI certificate
- [ ] the Control Plane's mTLS CA certificate (the same
      `cp-mtls-ca.pem` trust anchor Gateways pin — ask your admin)
- [ ] a dedicated non-root user and a data directory on the node
- [ ] outbound reachability to the Control Plane gRPC port and your Gateways

## Verify the binary before it runs

Agent releases ship with a Sigstore signature and SLSA provenance, and the
Agent itself is the verifier — fully offline, against a pinned
`trusted_root.json` you supply. Verify **before** the binary ever executes:

```bash
sessionlayer-agent verify \
  --binary ./sessionlayer-agent-candidate \
  --blob-bundle ./sessionlayer-agent-candidate.sigstore.json \
  --provenance ./sessionlayer-agent-candidate.provenance.sigstore.json \
  --trusted-root /etc/sessionlayer/trusted_root.json
```

Exit 0 means it would be trusted to run; exit 2 means refused — wrong identity,
tampered bytes, forged chain, or a downgrade. Updates go through the same gate
and are installed atomically only if they pass:

```bash
sessionlayer-agent update \
  --candidate ./sessionlayer-agent-new \
  --blob-bundle ./new.sigstore.json --provenance ./new.provenance.sigstore.json \
  --trusted-root /etc/sessionlayer/trusted_root.json \
  --install-to /usr/local/bin/sessionlayer-agent
```

Anti-rollback is on by default (a candidate older than the running version is
refused). A running Agent can also re-check itself: `run --verify-self` with the
same three bundle flags refuses to start if its own binary no longer verifies.

> **Warning:** production `trusted_root.json` must pin the certificate
> transparency logs — the pinned SessionLayer release identity requires CT and
> fails closed without it. See [Supply chain](../security/supply-chain.md) for
> where the trusted root comes from and the full release-verification story.

You can also build from source instead
(`cargo build --release`, Rust 1.95 + `protoc`, from
[SessionLayer/Agent](https://github.com/SessionLayer/Agent)) — then your build
is your provenance.

## Join the platform

```bash
sessionlayer-agent run \
  --node-name web-01 \
  --join-method token --join-token-file /run/join-token \
  --cp-endpoint https://cp.example.com:9443 \
  --cp-server-name cp.example.com \
  --bootstrap-ca-file /etc/sessionlayer/cp-mtls-ca.pem \
  --data-dir /var/lib/sessionlayer-agent
```

The Agent generates its keypair locally and sends only a CSR; the private key
never leaves the node (stored `0600`, zeroized in memory). It receives a
generation-0 mTLS identity and renews ahead of expiry for as long as it runs.

Three join methods, one outcome (the renewable identity is identical
regardless):

| Method | Flag | Bootstrap proof |
|---|---|---|
| Token | `--join-method token --join-token-file …` | a single-use, short-TTL join token an admin issued via `POST /v1/join-tokens` |
| OIDC | `--join-method oidc --join-token-file …` | a workload identity token (Kubernetes ServiceAccount, CI, cloud) — no shared secret; the Control Plane must have `sessionlayer.agent-join.oidc.*` configured |
| mTLS | `--join-method mtls --operator-cert-file … --operator-key-file …` | a certificate from your own PKI, pre-trusted by the Control Plane (`sessionlayer.agent-join.mtls.*`) |

> **Note:** a token-join Agent that lets its identity fully lapse (or gets
> locked) cannot self-heal — the token was consumed. Re-provision by issuing a
> fresh token via the API; it is a pure API operation precisely so your
> automation can do it without a human.

## Non-root is enforced, not suggested

The Agent **refuses to start as root** — before loading any credential. A root
agent could read the node's host keys and impersonate the node, collapsing the
platform's host-identity verification. Create a dedicated user:

```bash
sudo useradd --system --home /var/lib/sessionlayer-agent --shell /usr/sbin/nologin sessionlayer-agent
sudo install -d -o sessionlayer-agent -g sessionlayer-agent -m 0700 /var/lib/sessionlayer-agent
```

The container image runs as uid 65532 with a read-only rootfs (see
`Agent/deploy/`), and the process applies its own seccomp + Landlock sandbox at
startup, confining writes to the data directory and egress to the Control
Plane, the Gateways, the loopback splice, and an OTLP collector if configured.

## Exit codes your supervisor should know

| Exit | Meaning | What to do |
|---|---|---|
| 3 | **clone detected** — the identity's generation counter forked; both copies are now locked | treat as a security event: investigate, then re-provision — the lock never auto-clears |
| 4 | repair needed — the persisted identity state is unusable | re-provision the join credential |

Configure your service manager to **not** blindly restart on exit 3 — a
restart loop cannot clear a clone lock. The full reason catalog is in the
[Agent runbook](../operations/agent-runbook.md).

## Verify the join

The node appears in the inventory once its Agent holds control channels:

```bash
curl -s -H "Authorization: Bearer $TOKEN" https://cp.example.com/v1/nodes | jq '.nodes[] | {name, status, health}'
```

In HA deployments give the Agent **at least two Gateways in different failure
domains** — it holds a control channel to each and survives losing one.

## Next

- [Nodes](../admin-guides/nodes.md)
- [Supply chain](../security/supply-chain.md)
- [Agent configuration reference](../reference/config-agent.md)
- [Agent runbook](../operations/agent-runbook.md)
