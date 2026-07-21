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
egress rules need Linux ≥ 6.7 (this is the practical floor on arm64 — see the
[hardening checklist](../security/hardening.md)). On an older kernel the
missing layer degrades with a loud warning instead of refusing to start; the
container security context then carries that layer.

> **Note:** aarch64 is supported and the code is CI-checked on it; validate the
> hardened profile on your own arm hardware before production, as the sign-off
> E2Es ran on x86_64.

## Backing services

| Service | Version | Used for |
|---|---|---|
| PostgreSQL | 17 | the single source of truth: config, runtime state, audit |
| S3-compatible object store with Object Lock | MinIO or AWS S3 | WORM recording storage |
| OIDC identity provider | any spec-compliant IdP | user login (auth-code + PKCE, device flow) |
| HashiCorp Vault (optional) | 1.18+ with the SSH secrets engine | a production CA backend (`/ssh/sign`) |
| AWS KMS / Azure Key Vault (optional) | — | alternative production CA backends |
| NATS (HA mode only) | 2.10 | coordination signaling — never session bytes |

Single-instance mode needs Postgres only; everything else on this list is
either optional or tied to a capability you enable. Versions are what the
platform is developed and continuously tested against.

> **Warning:** production deployments must not keep CA private keys in-process.
> Plan for Vault, AWS KMS, or Azure Key Vault as the CA backend from day one —
> the local backend exists for development and refuses to start without an
> explicit override or a real key-encryption key. See
> [Certificate authorities](../admin-guides/certificate-authorities.md).

## Nodes

Nodes run their own **stock OpenSSH `sshd`** — there is nothing to install for
agentless access beyond one `TrustedUserCAKeys` line and a host-identity
anchor (host certificate or pinned key). The platform is tested against
OpenSSH 10 on Debian 13. For `scp` in SFTP mode you need OpenSSH 9.0+ on the
node; legacy `scp` mode works everywhere.

The optional [Agent](agent.md) (for outbound-only nodes) requires a dedicated
non-root user — it refuses to start as root.

## Clocks

All components assume NTP-synchronized clocks. Certificates are backdated a few
minutes to tolerate small skew, and the Gateway expires grants conservatively
(early, never late) — but a node whose clock is minutes off will reject inner
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
| Gateway ↔ Gateway | TLS (HA mode) | direct session relay — bytes never touch the bus |
| Gateway → object store | HTTPS | encrypted recording upload (presigned PUT) |
| admins/users → Control Plane | HTTPS (`:8080` behind your L7 LB) | REST API, Dashboard, OIDC pages |
| Control Plane → Postgres | 5432 | all state |

The Gateway needs **no inbound reachability from nodes**, and agent-model nodes
need no inbound reachability at all.

## Next

- [Install the Control Plane](control-plane.md)
- [Install the Gateway](gateway.md)
- [Quickstart](../getting-started/quickstart.md)
- [Ports reference](../reference/ports.md)
