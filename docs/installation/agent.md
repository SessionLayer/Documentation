# Install the Agent

Nodes that cannot accept an inbound connection still need a way in: the
Agent is a minimal Rust process installed on the node that dials out to
your Gateways instead of waiting for one to dial in. By the end of this
page it holds a renewable mTLS identity and splices sessions into the
node's own `sshd` on demand.

You only need the Agent for outbound-only nodes (NAT, egress-only firewalls,
or when you want the node-local second audit trail). Nodes the Gateway can
reach directly are better served agentless: nothing to install at all. See
[Nodes](../admin-guides/nodes.md) for choosing per node.

Prerequisites:

- [ ] the node registered by an admin with `"connectorKind": "agent"` and its
      host-identity anchor ([Nodes](../admin-guides/nodes.md)), under the same
      name you pass to `--node-name`
- [ ] a join credential from an admin: a join token
      (`POST /v1/join-tokens`), an OIDC workload identity, or an
      operator-PKI certificate
- [ ] the Control Plane's mTLS CA certificate (the same
      `cp-mtls-ca.pem` trust anchor Gateways pin; ask your admin)
- [ ] a dedicated non-root user and a data directory on the node
- [ ] outbound reachability to the Control Plane gRPC port and your Gateways

## Verify the binary before it runs

Agent releases ship with a Sigstore signature and SLSA provenance, and the
Agent itself is the verifier: fully offline, against a pinned
`trusted_root.json` you supply. Verify before the binary ever executes:

```bash
sessionlayer-agent verify \
  --binary ./sessionlayer-agent-candidate \
  --blob-bundle ./sessionlayer-agent-candidate.sigstore.json \
  --provenance ./sessionlayer-agent-candidate.provenance.sigstore.json \
  --trusted-root /etc/sessionlayer/trusted_root.json
```

Exit 0 means it would be trusted to run; exit 2 means refused: wrong
identity, tampered bytes, forged chain, or a downgrade. Updates go through the
same gate and are installed atomically only if they pass:

```bash
sessionlayer-agent update \
  --candidate ./sessionlayer-agent-new \
  --blob-bundle ./new.sigstore.json --provenance ./new.provenance.sigstore.json \
  --trusted-root /etc/sessionlayer/trusted_root.json \
  --install-to /usr/local/bin/sessionlayer-agent
```

Anti-rollback is on by default (a candidate older than the running version is
refused). A running Agent can also re-check itself: `run --verify-self` with
the same three bundle flags refuses to start if its own binary no longer
verifies.

> **Warning:** production `trusted_root.json` must pin the certificate
> transparency logs. The pinned SessionLayer release identity requires CT and
> fails closed without it. See [Supply chain](../security/supply-chain.md) for
> where the trusted root comes from and the full release-verification story.

You can also build from source instead
(`cargo build --release`, Rust 1.95 + `protoc`, from
[SessionLayer/Agent](https://github.com/SessionLayer/Agent)); then your build
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

`--node-name` is the join key. It attaches the Agent to the node an admin
registered under that name, which is where the node's host-identity anchor
lives. A name registered for the agentless connector is refused, and a name
that does not exist yet creates an anchorless node that can carry no session.
Confirm the registration before the first run.

Three join methods, one outcome (the renewable identity is identical
regardless):

| Method | Flag | Bootstrap proof |
|---|---|---|
| Token | `--join-method token --join-token-file …` | a single-use, short-TTL join token an admin issued via `POST /v1/join-tokens` |
| OIDC | `--join-method oidc --join-token-file …` | a workload identity token (Kubernetes ServiceAccount, CI, cloud), no shared secret; the Control Plane must have `sessionlayer.agent-join.oidc.*` configured |
| mTLS | `--join-method mtls --operator-cert-file … --operator-key-file …` | a certificate from your own PKI, pre-trusted by the Control Plane (`sessionlayer.agent-join.mtls.*`) |

> **Note:** a token-join Agent that lets its identity fully lapse (or gets
> locked) cannot self-heal: the token was consumed. Re-provision by issuing a
> fresh token via the API; it is a pure API operation precisely so your
> automation can do it without a human.

## Non-root is enforced, not suggested

The Agent refuses to start as root, before loading any credential. A root
agent could read the node's host keys and impersonate the node, collapsing
the platform's host-identity verification. Create a dedicated user:

```bash
sudo useradd --system --home /var/lib/sessionlayer-agent --shell /usr/sbin/nologin sessionlayer-agent
sudo install -d -o sessionlayer-agent -g sessionlayer-agent -m 0700 /var/lib/sessionlayer-agent
```

The Agent also disables core dumps and ptrace-dumpability
(`RLIMIT_CORE=0`, `PR_SET_DUMPABLE=0`) before any credential work, so a crash
cannot spill the mTLS key or a join token into a core file. In-process
seccomp and Landlock then confine writes to the data directory and egress to
the Control Plane, the Gateways, the loopback splice, and an OTLP collector if
configured. On a kernel that lacks Landlock (or its network-egress ABI,
Linux ≥ 6.7), the Agent degrades with a loud, logged Accepted-Risk instead of
refusing to start; `--require-full-landlock` turns that degrade into a
startup failure for regimes that cannot accept it.

## Run it in a container

```bash
docker pull ghcr.io/sessionlayer/agent:v0.0.2
```

`v0.0.2` is the release tag; substitute the one you are installing. There is no
`:latest`. The image is a `linux/amd64` + `linux/arm64` index with no shell in
the final layer and a numeric `USER 65532`, so `runAsNonRoot` can enforce it
without an `/etc/passwd` lookup. `/var/lib/sessionlayer-agent` is the only path
the process writes, which is what makes a read-only root filesystem hold.

Verify it before you run it, the same way and against the same identity as the
binary:

```bash
DIGEST=$(docker buildx imagetools inspect ghcr.io/sessionlayer/agent:v0.0.2 \
  --format '{{json .Manifest}}' | jq -r .digest)

cosign verify "ghcr.io/sessionlayer/agent@$DIGEST" \
  --certificate-identity "https://github.com/SessionLayer/Agent/.github/workflows/release.yml@refs/tags/v0.0.2" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"

gh attestation verify "oci://ghcr.io/sessionlayer/agent@$DIGEST" \
  --repo SessionLayer/Agent
```

```bash
docker run --read-only \
  --user 65532:65532 \
  --security-opt no-new-privileges \
  -v sl-agent-data:/var/lib/sessionlayer-agent \
  "ghcr.io/sessionlayer/agent@$DIGEST" run ...
```

Build your own from `deploy/Dockerfile` instead if you prefer, and then your
build is your provenance:

```bash
docker build -f deploy/Dockerfile -t sessionlayer-agent .
```

> **Warning:** `--verify-self` does not carry over to the container. The
> binary inside the image is compiled by the image build, so it is not the
> released binary and the release's blob signature does not cover its bytes.
> Pointing `--self-blob-bundle` at a downloaded release bundle refuses to
> start (exit 2), correctly. The image's own signature and provenance are what
> cover what is in it: verify the digest, deploy the digest.

## Deploy on Kubernetes

`deploy/helm/sessionlayer-agent` renders a DaemonSet, a ServiceAccount and a
NetworkPolicy. The Agent takes flags rather than a config file, so the chart
builds an argument list. It creates no Secret:

```bash
kubectl -n sessionlayer create configmap sessionlayer-bootstrap-ca \
  --from-file=ca.pem=cp-mtls-ca.pem

helm install agent deploy/helm/sessionlayer-agent \
  --namespace sessionlayer \
  --set trustAnchor.existingConfigMap=sessionlayer-bootstrap-ca \
  --set image.digest="$DIGEST" \
  --set hostNetwork=true \
  --set 'gateways[0].endpoint=wss://gw-a.example.com:9444' \
  --set 'gateways[0].serverName=gw-a'
```

`join.method` defaults to `oidc`, where the kubelet projects a ServiceAccount
token for the audience the Control Plane validates
(`join.audience`, matching `sessionlayer.agent-join.oidc.audience`). The
`token` and `mtls` methods read a Secret you name in `join.existingSecret`.

Set `hostNetwork=true` for the DaemonSet's stated job. The Agent refuses any
splice address that is not loopback, and a pod's loopback is not the node's, so
without it `--splice-addr` reaches nothing and every session to the node fails
to connect. Weigh that against sharing the node's network namespace.

The chart refuses to render rather than installing something that looks healthy
and works for nothing:

| Condition | Why it refuses |
|---|---|
| `gateways` empty | The Agent would join the Control Plane, hold an identity, and serve no session. |
| A `gateways` entry with no `serverName` | The binary's fallback is a development name, so the TLS handshake fails with nothing naming the cause. |
| `failureDomain` on some entries but not all | The binary aligns the flags by position and refuses a partial list. |
| `minControlChannels` above the number of entries | The Agent can never reach its own floor, so it never becomes healthy. |
| No `trustAnchor.existingConfigMap` | The Agent pins the Control Plane's CA and performs no trust-on-first-use. |
| `terminationGracePeriodSeconds` below `drainDeadlineSecs` | A SIGKILL landing in the credential-persist window leaves a generation the Control Plane reads as a clone and auto-locks, turning a routine node drain into a manual re-provision. |

`minControlChannels` stays at `1` by default. Raising it, with Gateways in
different failure domains, is what makes a single Gateway outage a non-event.

The plain manifests remain the non-Helm reference:
`deploy/kubernetes/agent-daemonset.yaml` carries the same posture, and
`deploy/kubernetes/agent-networkpolicy.yaml` denies all inbound traffic and
scopes egress to the Control Plane, the configured Gateways, and DNS. Their
`image:` line names the release tag; replace it with the digest you verified.
[Deploy with Helm](helm.md) covers what all four charts have in common, and the
static-validation-only status they ship with.

## Exit codes your supervisor should know

| Exit | Meaning | What to do |
|---|---|---|
| 3 | clone detected: the identity's generation counter forked, and both copies are now locked | treat as a security event: investigate, then re-provision. The lock never auto-clears |
| 4 | repair needed: the persisted identity state is unusable | re-provision the join credential |

On systemd, set `RestartPreventExitStatus=3 4` so the unit does not blindly
restart into a lock it cannot clear. A Kubernetes DaemonSet cannot do this:
`restartPolicy` is fixed to `Always`, so kubelet keeps restarting the
container regardless of exit code. Ship
`observability/prometheus-agent-alert-rules.yaml` alongside the DaemonSet to
page on exit codes 3 and 4 via `kube_pod_container_status_last_terminated_exitcode`
(needs kube-state-metrics scraping the namespace); alerting is the only lever
you have there. The full reason catalog is in the
[Agent runbook](../operations/agent-runbook.md).

## Verify the join

The node appears in the inventory once its Agent holds control channels.
`$TOKEN` is an admin bearer token; see
[Authentication](../admin-guides/authentication.md):

```bash
curl -s -H "Authorization: Bearer $TOKEN" https://cp.example.com/v1/nodes | jq '.nodes[] | {name, status, health}'
# expect: {"name": "web-01", "status": "active", "health": "healthy"}
```

In HA deployments give the Agent at least two Gateways in different failure
domains: it holds a control channel to each and survives losing one.

## Next

- [Nodes](../admin-guides/nodes.md)
- [Supply chain](../security/supply-chain.md)
- [Agent configuration reference](../reference/config-agent.md)
- [Agent runbook](../operations/agent-runbook.md)
