# SessionLayer documentation

SessionLayer is a self-hosted, API-first Zero-Trust SSH access platform for
fleets of Linux nodes, used from **stock OpenSSH clients** — no custom client to
install. It terminates and re-originates SSH at a hardened Gateway, which is
what makes real session recording, command logging, and file-transfer audit
possible where a plain jump host (seeing only ciphertext) cannot.

- **Certificates, not keys.** No long-lived SSH keys anywhere: every session
  runs on a short-lived certificate minted per connection, after policy passes.
- **Recordings only you can read.** Sessions are recorded keystroke-for-keystroke
  and sealed to a key you hold — the platform cannot decrypt its own recordings.
- **Deny fails closed.** Locks and denials are enforced even when everything
  else is on fire; that guarantee is tested, not aspirational.

**New here? Start with the [Quickstart](docs/getting-started/quickstart.md)** —
a single-host evaluation: bring the stack up with Docker Compose, connect with
your stock `ssh`, then watch the session replay.

## Documentation map

| Section | What is in it |
|---|---|
| [Getting started](docs/getting-started/quickstart.md) | The [Quickstart](docs/getting-started/quickstart.md), [Core concepts](docs/getting-started/concepts.md), and an honest look at [how SessionLayer compares](docs/getting-started/how-it-compares.md) |
| [Installation](docs/installation/requirements.md) | [Requirements](docs/installation/requirements.md) and per-component installs: [Control Plane](docs/installation/control-plane.md), [Gateway](docs/installation/gateway.md), [Agent](docs/installation/agent.md), [Dashboard](docs/installation/dashboard.md) |
| [Admin guides](docs/admin-guides/nodes.md) | Day-2 tasks: [nodes](docs/admin-guides/nodes.md), [RBAC](docs/admin-guides/rbac.md), [authentication](docs/admin-guides/authentication.md), [JIT](docs/admin-guides/jit-access.md), [break-glass](docs/admin-guides/break-glass.md), [recording](docs/admin-guides/session-recording.md), [session limits](docs/admin-guides/session-limits.md), [locks](docs/admin-guides/locks.md), [audit](docs/admin-guides/audit.md), [CAs](docs/admin-guides/certificate-authorities.md), [HA](docs/admin-guides/high-availability.md) |
| [User guide](docs/user-guide/ssh-access.md) | For people connecting through SessionLayer: [SSH access](docs/user-guide/ssh-access.md), [file transfer](docs/user-guide/file-transfer.md), [requesting access](docs/user-guide/requesting-access.md) |
| [Reference](docs/reference/api.md) | The [REST API](docs/reference/api.md), configuration for [Control Plane](docs/reference/config-control-plane.md) / [Gateway](docs/reference/config-gateway.md) / [Agent](docs/reference/config-agent.md), [audit events](docs/reference/audit-events.md), [metrics](docs/reference/metrics.md), [ports](docs/reference/ports.md), [glossary](docs/reference/glossary.md) |
| [Security](docs/security/trust-model.md) | The [trust model](docs/security/trust-model.md) (including what SessionLayer does *not* protect against), the [production hardening checklist](docs/security/hardening.md), and [supply-chain verification](docs/security/supply-chain.md) |
| [Operations](docs/operations/monitoring.md) | [Monitoring](docs/operations/monitoring.md), the [Gateway](docs/operations/gateway-runbook.md) and [Agent](docs/operations/agent-runbook.md) runbooks, [upgrades](docs/operations/upgrades.md), [troubleshooting](docs/operations/troubleshooting.md) |
| [FAQ](docs/faq.md) | Short answers, including "can SessionLayer staff read my recordings?" (no — and here is why) |

## The platform

SessionLayer is three components, each in its own repository:

| Repository | Component |
|---|---|
| [ControlPlane-API](https://github.com/SessionLayer/ControlPlane-API) | **Control Plane** (Java) — policy, identity, CAs, audit, the REST API |
| [Gateway](https://github.com/SessionLayer/Gateway) | **Gateway** (Rust) — the SSH data plane: terminates, records, re-originates |
| [Agent](https://github.com/SessionLayer/Agent) | **Agent** (Rust) — optional per-node outbound connector (no inbound holes) |
| [ControlPlane-Dashboard](https://github.com/SessionLayer/ControlPlane-Dashboard) | **Dashboard** (React) — the admin web UI, a client of the API |

## Contributing to these docs

Read [STYLE.md](STYLE.md) first — it is the voice and accuracy contract. Every
command in these docs is executed before it ships, and CI drift-checks the API
and configuration references against the source repositories both ways.

## License

[GPL-3.0](LICENSE).
