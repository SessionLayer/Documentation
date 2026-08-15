# Requirements

What you need before installing SessionLayer. For a disposable single-host
evaluation that skips all of this, use the
[Quickstart](../getting-started/quickstart.md) instead.

## Platforms

| Component | Runs on | Built with |
|---|---|---|
| Control Plane | Linux x86_64 or aarch64, Java 25 runtime | the repo's Maven wrapper (JDK 25) |
| Gateway | Linux x86_64 or aarch64 | Rust 1.95.0 (pinned toolchain) + `protoc` |
| Agent | Linux x86_64 or aarch64 | Rust 1.95.0 (pinned toolchain) + `protoc` |
| Dashboard | any static file host (it is a browser bundle) | Node 22 |

The Gateway and Agent apply in-process seccomp and Landlock hardening at
startup. Landlock filesystem confinement needs Linux ≥ 5.13 and the network
egress rules need Linux ≥ 6.7 (the practical floor on arm64; see the
[hardening checklist](../security/hardening.md)). On an older kernel the
missing layer degrades with a loud warning instead of refusing to start; the
container security context then carries that layer.

> **Note:** aarch64 is supported and the code is CI-checked on it; validate the
> hardened profile on your own arm hardware before production, as the sign-off
> E2Es ran on x86_64.

## Container images and charts

| Component | Image | Chart |
|---|---|---|
| Control Plane | `ghcr.io/sessionlayer/controlplane` | `deploy/helm/sessionlayer-controlplane` |
| Gateway | `ghcr.io/sessionlayer/gateway` | `deploy/helm/sessionlayer-gateway` |
| Agent | `ghcr.io/sessionlayer/agent` | `deploy/helm/sessionlayer-agent` |
| Dashboard | `ghcr.io/sessionlayer/dashboard` | `deploy/helm/sessionlayer-dashboard` |

Each image is a `linux/amd64` + `linux/arm64` index carrying the release tag,
signed and attested in the registry. Verifying one needs `cosign`, plus the
GitHub CLI for the provenance and `docker buildx` for the SBOM
([Supply chain](../security/supply-chain.md)).

> **Warning:** these packages are private today, so an unauthenticated pull
> fails and so does every verification step that has to reach the manifest.
> Build from source until they are public; each component's installation page
> has the commands, and a build you performed is its own provenance.

Each chart lives in its component's repository and declares
`kubeVersion: >=1.21.0-0`, the floor for a `policy/v1` PodDisruptionBudget.
Every chart renders a NetworkPolicy unless you turn it off, permitting only the
peers its component talks to. That needs a CNI that enforces NetworkPolicy; on
one that does not, the object is accepted and enforces nothing
([Deploy with Helm](helm.md)).

## Backing services

| Service | Version | Used for |
|---|---|---|
| PostgreSQL | 17 | the single source of truth: config, runtime state, audit |
| S3-compatible object store with Object Lock | MinIO or AWS S3 | WORM recording storage |
| OIDC identity provider | any spec-compliant IdP | user login (auth-code + PKCE, device flow) |
| Azure Key Vault (optional) | n/a | a production CA backend for the three SSH CAs; shipped and signer-complete |
| AWS KMS (optional) | n/a | a production CA backend for the three SSH CAs; shipped and signer-complete |
| HashiCorp Vault (optional) | 1.18+ with the SSH secrets engine | a production CA backend (`/ssh/sign`); an integration seam in this build, no shipped signer |
| NATS (HA mode only) | 2.10 | coordination signaling, never session bytes |

Single-instance mode needs Postgres only; everything else on this list is
either optional or tied to a capability you enable. Versions are what the
platform is developed and continuously tested against.

> **Warning:** `local`, protected by a real key-encryption key, is a
> legitimate production CA backend for every CA kind. See
> [Production hardening](../security/hardening.md). Azure Key Vault and AWS KMS
> are the alternatives that actually sign in this build, for the three SSH CAs
> (`user`/`session`/`host`); HashiCorp Vault remains an integration seam a
> deployment would have to bind its own SDK against. The internal mTLS CA
> cannot move off `local` regardless. See
> [Certificate authorities](../admin-guides/certificate-authorities.md)
> for both adoption procedures.

## Nodes

Nodes run their own stock OpenSSH `sshd`. There is nothing to install for
agentless access beyond one `TrustedUserCAKeys` line and a host-identity
anchor (host certificate or pinned key). The platform is tested against
OpenSSH 10 on Debian 13. For `scp` in SFTP mode you need OpenSSH 9.0+ on the
node; legacy `scp` mode works everywhere.

The optional [Agent](agent.md) (for outbound-only nodes) requires a dedicated
non-root user. It refuses to start as root.

## Clocks

All components assume NTP-synchronized clocks. Certificates are backdated a few
minutes to tolerate small skew, and the Gateway expires grants conservatively
(early, never late), but a node whose clock is minutes off will reject inner
certificates. Run `chrony` or `systemd-timesyncd` everywhere.

## Network matrix

The full per-listener table lives in the [ports reference](../reference/ports.md).
The shape of the traffic:

| From → to | Protocol | Purpose |
|---|---|---|
| users → Gateway | SSH (`:22`, or a high port behind an L4 LB) | the outer SSH leg |
| Gateway → Control Plane | gRPC over mTLS (`:9443` by convention) | authorization, certificate signing, locks |
| Gateway → nodes | SSH (`:22`) | the inner leg (agentless model) |
| Agents → Gateway | WebSocket over TLS (outbound only) | agent control channel + dial-back |
| Gateway ↔ Gateway | TLS (HA mode) | direct session relay; bytes never touch the bus |
| Gateway → object store | HTTPS | encrypted recording upload (presigned PUT) |
| admins/users → Control Plane | HTTPS (`:8080` behind your L7 LB) | REST API, Dashboard, OIDC pages |
| Control Plane → Postgres | 5432 | all state |

The Gateway needs no inbound reachability from nodes, and agent-model nodes
need no inbound reachability at all.

## Next

- [Install the Control Plane](control-plane.md)
- [Install the Gateway](gateway.md)
- [Quickstart](../getting-started/quickstart.md)
- [Ports reference](../reference/ports.md)
