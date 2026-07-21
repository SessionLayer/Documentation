# Certificate authorities

SessionLayer runs on short-lived certificates instead of long-lived keys, and
this guide explains the authorities that make that work: the **three SSH CAs**
(user, session, host), the internal X.509 CA behind the component mesh, the
supported key backends, and how to rotate a CA without fleet downtime.

## The three SSH CAs, and why there are three

| CA | Signs | Who trusts it |
|---|---|---|
| **User CA** | optional short-lived certificates users present to the Gateway (for example, Vault-issued) | the Gateway's outer-leg verifier only |
| **Session CA** | the ephemeral per-session certificate the Gateway presents to the node | **node `sshd`, via one `TrustedUserCAKeys` line — the only thing nodes trust** |
| **Host CA** | node host certificates, and the host certificate the Gateway presents on the ProxyJump path | the Gateway's node verifier; users' `known_hosts` (`@cert-authority`) |

The separation between the user CA and the session CA is the security crux of
the platform. Node `sshd` trusts **only the session CA** — so a stolen user
credential, a leaked pinned key, or a compromised user CA is useless directly
against any node. Only the Gateway can mint a certificate a node accepts, and
it does so per connection, only after authorization passes, with a key it
generated locally moments earlier. Three invariants keep this true end to
end:

1. The Gateway is the **only** minter of session-CA certificates, per
   connection, post-authorization. No credential a user or agent holds is
   ever a session-CA certificate.
2. Pinned keys are an authentication shortcut only — they live in the
   Gateway's outer-leg verifier, never in any node's trust, and every
   reconnect re-runs authorization.
3. Break-glass is an authorization override consumed at the Gateway — still a
   per-connection session certificate, still recorded, never a standing trust
   entry on any node. The trust set handed to nodes contains session-kind
   keys only; this exclusion is directly tested.

A fourth authority, the **internal X.509 CA**, anchors the mTLS mesh between
components (Control Plane ↔ Gateway ↔ Agent identities, the signed decision
contexts). It is internal machinery, not part of the SSH trust model above.

## The ephemeral session certificate

What the node actually sees, per connection:

- **Principal** — the RBAC-resolved Linux login (`deploy`), never the human
  identity. `sshd` re-enforces it natively.
- **Key ID** — `session id + identity`, so the node's own `sshd` log records
  *which human* logged in even to a shared account — the node-local second
  audit trail.
- **Lifetime** — about 5 minutes, backdated a couple of minutes for clock
  skew, scoped to the handshake. Expiry never affects a live session:
  session lifetime is governed by the authorization's grant expiry and
  [locks](locks.md), not the certificate clock.
- **Extensions** — only what the matched rule granted; default-deny
  otherwise. The certificate deliberately omits a `source-address` pin: the
  node would validate it against the *Gateway's* egress IP, not the user's,
  so source-IP enforcement lives on the user-facing leg and in the
  authorization decision instead.
- **Key custody** — the Gateway generates the keypair and sends only the
  public key; the Control Plane returns a certificate only. The inner private
  key never leaves the Gateway, and with the Vault backend the platform uses
  the sign-only endpoint (`/ssh/sign`), never `/ssh/issue`, which would have
  Vault mint (and know) a private key.

This is why "no long-lived keys" holds everywhere: certificate expiry is the
revocation baseline, a lock is the immediate override, and rotating a CA is
reserved for actual CA-key compromise — never a routine access-removal tool.

## Backends

Each CA is configured independently — different backends per CA are fine and
encouraged for custody separation:

| Backend | Key lives in | Notes |
|---|---|---|
| `local` | the Control Plane's database, envelope-encrypted under a KEK | dev/eval default |
| `aws_kms` | AWS KMS | signatures normalized from DER |
| `azure_keyvault` | Azure Key Vault | no Ed25519 support — see algorithms |
| `vault` | HashiCorp Vault's SSH engine | sign-only (`/ssh/sign`) |

The default algorithm is `ecdsa-p256` — the portable choice every backend can
produce. A configuration requesting an algorithm its backend cannot produce
(for example `ed25519` on `azure_keyvault`) is rejected at validation with a
`422`, before anything is stored.

> **Warning:** the `local` backend keeps CA private keys in-process and
> in-database (encrypted under the KEK reference in operator settings). It
> exists for development and evaluation. In production, back every CA with
> KMS, Key Vault, or Vault so the private key is never in the Control Plane's
> memory — and note the Control Plane **fails closed at startup** if left on
> the well-known dev KEK without an explicit override. This is a
> [hardening precondition](../security/hardening.md).

Manage CA configurations over the API (`ca:manage`):

```bash
curl -s https://cp.example.com/v1/cas \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: ca-session-vault-1" \
  -d '{
    "name": "session-ca",
    "caKind": "session",
    "backend": "vault",
    "keyReference": "ssh-client-signer/roles/sessionlayer-session",
    "algorithm": "ecdsa-p256"
  }'
```

`keyReference` is always a backend handle — the API rejects anything that
looks like private key material, and no read ever returns private material.

## Cold start

A fresh Control Plane with an empty database provisions all three CAs itself
— idempotently, restart-safely, and race-safely across replicas. There is no
manual key ceremony for a first install; pointing the CA configs at
production backends is the ceremony.

## Rotation: overlap, then drain

Rotation never stops the fleet, because trust is a *set*: during rotation both
the outgoing and incoming keys verify.

```bash
# CA_ID from GET /v1/cas.
curl -s https://cp.example.com/v1/cas/$CA_ID/rotate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: rotate-session-ca-2026q3" \
  -d '{}'
```

(`ca:rotate` permission; optionally override `algorithm` or supply a
pre-provisioned `keyReference` in the body.) The state machine: a new key is
provisioned in the same backend as `incoming`, the current `active` moves to
`outgoing` — both trusted — and the new key is promoted to `active`. New
certificates are signed by the new key; the outgoing key continues to verify
existing ones until it expires out.

> **Warning:** for the session and host CAs, "both trusted" must also be true
> **on your nodes and clients** — the `TrustedUserCAKeys` file and
> `@cert-authority` lines must contain the incoming key *before* the outgoing
> key drains. The platform does not (and cannot) verify that your fleet's
> trust distribution has completed; sequence your config management
> accordingly, and don't rush the drain. This gap is a documented accepted
> risk — the platform trusts you to finish distribution.

For an emergency rotation after suspected CA compromise, pair it with a
[lock](locks.md): lock first (immediate, un-overridable), rotate second
(the durable fix).

## Signing availability is an SLO

The session CA gates every **new** session — existing sessions continue if a
signer goes down, but nothing new starts, fail-closed. Treat signer
availability as a peer of your database: the Control Plane exposes a health
indicator and meters for it, redundant signer backends behind the same CA key
are the HA pattern, and the shipped alerts page on signer fail-closed spikes
— see [Monitoring](../operations/monitoring.md).

## Next

- [Production hardening](../security/hardening.md) — moving every CA off
  `local` before go-live.
- [Nodes](nodes.md) — the `TrustedUserCAKeys` line and host anchors this
  page's trust model relies on.
- [Locks](locks.md) — the immediate revocation tool, so rotation never has
  to be one.
- [Trust model](../security/trust-model.md) — the two-CA separation in the
  wider threat model.
