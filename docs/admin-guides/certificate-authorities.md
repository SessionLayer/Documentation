# Certificate authorities

SessionLayer runs on short-lived certificates instead of long-lived keys, and
this guide explains the authorities that make that work: the three SSH CAs
(user, session, host), the internal X.509 CA behind the component mesh, the
supported key backends, and how to rotate a CA without fleet downtime.

## Prerequisites

- [ ] the `ca:manage` platform permission, plus `ca:rotate` to rotate and
      `node:enroll` to export a public key
- [ ] an admin bearer token in `$TOKEN`; see [Authentication](authentication.md)

## The three SSH CAs, and why there are three

| CA | Signs | Who trusts it |
|---|---|---|
| User CA | optional short-lived certificates users present to the Gateway (for example, Vault-issued) | the Gateway's outer-leg verifier only |
| Session CA | the ephemeral per-session certificate the Gateway presents to the node | node `sshd`, via one `TrustedUserCAKeys` line (the only thing nodes trust) |
| Host CA | node host certificates, and the host certificate the Gateway presents on the ProxyJump path | the Gateway's node verifier; users' `known_hosts` (`@cert-authority`) |

The separation between the user CA and the session CA is the security crux
of the platform. Node `sshd` trusts only the session CA, so a stolen user
credential, a leaked pinned key, or a compromised user CA is useless
directly against any node. Only the Gateway can mint a certificate a node
accepts, and it does so per connection, only after authorization passes,
with a key it generated locally moments earlier. Three invariants keep this
true end to end:

1. The Gateway is the only minter of session-CA certificates, per
   connection, post-authorization. No credential a user or Agent holds is
   ever a session-CA certificate.
2. Pinned keys are an authentication shortcut only: they live in the
   Gateway's outer-leg verifier, never in any node's trust, and every
   reconnect re-runs authorization.
3. Break-glass is an authorization override consumed at the Gateway: still a
   per-connection session certificate, still recorded, never a standing
   trust entry on any node. The trust set handed to nodes contains
   session-kind keys only; this exclusion is directly tested.

A fourth authority, the internal X.509 CA, anchors the mTLS mesh between
components (Control Plane ↔ Gateway ↔ Agent identities, the signed decision
contexts). It is internal machinery, not part of the SSH trust model above.

## The ephemeral session certificate

What the node actually sees, per connection:

| Field | What it carries |
|---|---|
| Principal | The RBAC-resolved Linux login (`deploy`), never the human identity. `sshd` re-enforces it natively. |
| Key ID | `session_id + identity`, so the node's own `sshd` log records *which human* logged in even to a shared account: the node-local second audit trail. |
| Lifetime | About 5 minutes, backdated a couple of minutes for clock skew, scoped to the handshake. Expiry never affects a live session: session lifetime is governed by the authorization's grant expiry and [locks](locks.md), not the certificate clock. |
| Extensions | Only what the matched rule granted; default-deny otherwise. The certificate deliberately omits a `source-address` pin: the node would validate it against the *Gateway's* egress IP, not the user's, so source-IP enforcement lives on the user-facing leg and in the authorization decision instead. |
| Key custody | The Gateway generates the keypair and sends only the public key; the Control Plane returns a certificate only. The inner private key never leaves the Gateway. The same rule shapes the CA backends: the Vault seam exposes only a sign operation, never Vault's `/ssh/issue`, which would have Vault mint (and know) a private key. |

This is why "no long-lived keys" holds everywhere: certificate expiry is the
revocation baseline, a lock is the immediate override, and rotating a CA is
reserved for actual CA-key compromise, never a routine access-removal tool.

## Backends

`local` and `azure_keyvault` sign in a shipped build. `aws_kms` and `vault`
remain integration seams: the classes exist and are tested, but each consumes
an interface that nothing in the release implements, and no bean constructs
one. The write path refuses both of them with a `422`.

| Backend | Key lives in | Signer in a shipped build |
|---|---|---|
| `local` | the Control Plane's database, envelope-encrypted under a KEK | yes |
| `aws_kms` | AWS KMS | no: `KmsSigner` seam, unimplemented |
| `azure_keyvault` | Azure Key Vault | yes |
| `vault` | HashiCorp Vault's SSH engine | no: `VaultSshEngine` seam, unimplemented |

The refusal is deliberate. A CA configured on a seam would take the write and
then fail every signature, and for the session CA that means no new session
anywhere. The same predicate answers both the write path and the signer
lookup, so the set the API accepts and the set that can sign cannot drift
apart. Rows naming a seam stay readable, so a database carried from an older
deployment still starts; those CAs cannot sign.

`azure_keyvault` never falls back to `local`. A misconfigured or unreachable
vault, a malformed or unversioned `keyReference`, or missing pinned public-key
material each fail the signer lookup closed instead of quietly signing from
the database; only a CA row actually naming `local` ever reaches the local key
material.

Three algorithms are supported, all ECDSA: `ecdsa-p256` (the default and the
portable choice every backend can produce), `ecdsa-p384`, and `ecdsa-p521`.
Anything else is rejected at validation with a `422`, before anything is
stored, as is an algorithm the chosen backend cannot produce.

> **Warning:** this makes the KEK load-bearing rather than optional for
> whichever CAs remain on `local` — which is at minimum the internal mTLS CA,
> since it cannot move (see below), and by default all three SSH CAs too. Each
> such private key is in the Control Plane's database, envelope-encrypted
> under the key-encryption key you supply in `sessionlayer.ca.local.kek-base64`.
> Whoever holds the database and that key holds every CA you have not adopted
> onto Key Vault. Supply a real KEK from your secrets manager, keep it out of
> the database's backup path, and treat it as the platform's most sensitive
> secret. The Control Plane fails closed at startup on the well-known dev KEK
> without an explicit override. See [Production hardening](../security/hardening.md).

Moving a SSH CA onto `azure_keyvault` is a configuration change plus a
rotation: see [Adopt Key Vault for a CA](#adopt-key-vault-for-a-ca) below.
`aws_kms` and `vault` remain build steps: bind your SDK against the
`KmsSigner` or `VaultSshEngine` interface, and the backend it belongs to
becomes writable and signable in that build. Signature normalization, the
per-backend algorithm table and the fail-closed contract are already
implemented on this side of each seam; the call to your key service is the
missing piece.

Read the CA configurations over the API (`ca:manage`):

```bash
curl -s https://cp.example.com/v1/cas \
  -H "Authorization: Bearer $TOKEN" | jq '.items[] | {id, name, caKind, backend, rotationState}'
```

`POST /v1/cas` exists but cannot give you a working CA. A booted Control Plane
already holds an `active` CA of each of the three kinds from cold start, and
only one may be `active` per kind, so the create is a `409`. Even without that
collision it would not help: creating a configuration writes no key material,
so the CA it describes has nothing to sign with. Certificate authorities come
from cold start, and their keys are replaced by rotation.

`keyReference` is always a backend handle. The API rejects anything that looks
like private key material, and no read ever returns private material.

## Cold start

A fresh Control Plane with an empty database provisions all three CAs
itself: idempotently, restart-safely, and race-safely across replicas.
There is no manual key ceremony for a first install; pointing the CA
configs at production backends is the ceremony.

## Export a CA public key

Nodes and clients have to be told what to trust, which means getting a CA's
public key out of the platform. One call per kind (`session`, `host`, `user`),
gated `node:enroll`:

```bash
curl -s https://cp.example.com/v1/cas/session/public-key \
  -H "Authorization: Bearer $TOKEN"
```

The response carries the active CA's `opensshPublicKey`, ready to paste into a
node's `TrustedUserCAKeys` file or a client's `@cert-authority` line, alongside
`publicKeySpkiDer`, `algorithm`, `rotationState` and `fingerprintSha256`. It is
public verification material: nothing that signs is exposed, and no read of any
CA ever returns private material.

> **Note:** the export projects the CA's stored public key, present for
> `local` and `azure_keyvault` CAs alike — adopting Key Vault persists the
> fetched public key at rotation time, the same column a `local` CA's key
> populates. If a database carries a `aws_kms`- or `vault`-backend row from
> before this build's gate existed, no key was ever provisioned for it, so
> this returns `404` for that kind, and that CA cannot sign either. Rotate it,
> naming `local` or `azure_keyvault` explicitly, to bring the kind back onto a
> key that works.

The internal mTLS CA is not served here. It is an X.509 trust anchor rather
than an SSH CA, and it has its own export at `/v1/cas/mtls/trust-anchor` (see
[Install the Gateway](../installation/gateway.md)).

Where each key goes: the session CA into every node's `TrustedUserCAKeys`
([Nodes](nodes.md)), the host CA into users' `known_hosts` as an
`@cert-authority` line ([SSH access](../user-guide/ssh-access.md)).

## Adopt Key Vault for a CA

Moving a `user`, `session`, or `host` CA onto Azure Key Vault is a configuration
change on the Control Plane plus a rotation onto a key that already exists in
the vault. The internal mTLS CA cannot be adopted this way: it is absent from
`/v1/cas`, and its key stays on `local` for the deployment's lifetime.

Configure the vault this Control Plane signs in:

```properties
sessionlayer.ca.azure.enabled=true
sessionlayer.ca.azure.vault-uri=https://sessionlayer-cp.vault.azure.net
```

`vault-uri` is an allow-list anchor, not just a connection string: a
`keyReference` naming any other vault is refused, so a compromised
`config.ca_config` row cannot redirect signing to a vault an attacker
controls. See
[Control Plane configuration](../reference/config-control-plane.md#azure-key-vault-ca-backend-sessionlayercaazure)
for the credential options.

> **Note:** grant the Control Plane's identity the minimum role over the one
> key it signs with: the built-in **Key Vault Crypto User** role, or a custom
> role scoped to that key granting only `Microsoft.KeyVault/vaults/keys/read`
> and `Microsoft.KeyVault/vaults/keys/sign/action`. For a production Control
> Plane, use a **user-assigned managed identity via Workload Identity
> Federation**: no secret exists to leak or to rotate.

Create (or choose) an EC P-256 key in the vault — `azure_keyvault` only ever
signs P-256, whatever the CA's current algorithm is — and rotate the CA onto
its fully versioned identifier (`ca:rotate`):

```bash
# CA_ID from GET /v1/cas.
curl -s -X POST https://cp.example.com/v1/cas/$CA_ID/rotate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: adopt-session-ca-keyvault-2026q3" \
  -d '{
        "backend": "azure_keyvault",
        "keyReference": "https://sessionlayer-cp.vault.azure.net/keys/session-ca/0123456789abcdef0123456789abcdef",
        "algorithm": "ecdsa-p256"
      }'
```

Send `algorithm` explicitly whenever the CA you are adopting is not already
`ecdsa-p256` — an omitted `algorithm` inherits the active CA's current one,
and `ecdsa-p384`/`ecdsa-p521` are refused for this backend before anything is
written.

A CA's private key cannot be migrated: a key in Key Vault is *in* Key Vault, so
adoption is necessarily a rotation onto a new key, with the same
overlap-then-drain trust distribution any rotation needs (below). The Control
Plane fetches the key's public half from the vault once, at this call,
confirms it is an EC P-256 key with the `sign` operation permitted, and
persists it. That read is bounded by `sessionlayer.ca.azure.timeout` (default
`PT10S`): a vault that is merely slow rather than unreachable makes the
rotate call fail with a named refusal once the bound elapses, instead of
hanging. Every certificate afterward is signed by calling the vault and
verified against that pinned public key before it is returned; a signature
that does not verify, or that the vault returns in the wrong shape, fails
closed rather than reaching a node.

This path is proven end-to-end: a session CA rotated onto Key Vault this way,
over the REST API with no database credential, then brokered a real SSH
session through the Gateway to a node, with the certificate signed inside the
vault. The same guard has been shown to hold at that boundary rather than only
in isolation: a vault signing under a key other than the one pinned at
adoption is refused, and the session fails closed instead of proceeding on an
unverified certificate. This was proven against a Key Vault-compatible REST
double driven by the genuine Azure SDK, not against Azure itself; an opt-in
test against a real vault exists separately and is skipped without
credentials.

> **Warning:** the key version is mandatory and must be a real Key Vault
> version — 32 lowercase hex characters — not merely present: a blank value
> and a merely-plausible one like `v1` are both refused (`422`) before
> anything is written. What makes the pin matter operationally: the signing
> client is built from the exact identifier you name here, so a signature can
> never silently float onto whatever the vault currently calls "latest". The
> CA's public key is already distributed to every node's
> trusted set at that same version; if the vault's own key rotation floated
> the signing key underneath a running CA, the Control Plane would start
> emitting certificates no node trusts, with no error visible on the Control
> Plane side. To move onto a genuinely new vault key later, rotate again
> naming the new version explicitly — an empty-bodied rotate against a Key
> Vault CA re-adopts the exact version it already points to, which changes
> nothing.

## Rotation: overlap, then drain

Rotation never stops the fleet, because trust is a *set*: during rotation
both the outgoing and incoming keys verify.

```bash
# CA_ID from GET /v1/cas.
curl -s https://cp.example.com/v1/cas/$CA_ID/rotate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: rotate-session-ca-2026q3" \
  -d '{}'
```

> **Warning:** an empty body (`{}`) regenerates the *same* backend, key
> reference, and algorithm the active CA already has — a `local` CA comes back
> a fresh `local` key at the same curve, and an `azure_keyvault` CA re-adopts
> the exact key version it already points to, changing nothing operationally.
> `backend`, `keyReference`, and `algorithm` are real, validated overrides for
> the incoming key: naming a backend this build has no signer for, or a Key
> Vault reference that is unversioned or names a different vault, is a `422`
> before anything is written. This also means rotating a CA carried from an
> older deployment on `aws_kms` or `vault` does **not** self-heal on an empty
> body: an omitted `backend` inherits that same non-signing backend and the
> rotation is refused. Name the backend explicitly — `{"backend": "local"}`,
> or adopt Key Vault (above) — to bring the kind back onto a key that signs.

The state machine (`ca:rotate` permission): a new key is provisioned as
`incoming`, the current `active` moves to `outgoing` (both trusted), and the
new key is promoted to `active`. New certificates are signed by the new key;
the outgoing key continues to verify existing ones until it expires out.
Rotation acts on the CA's *kind*, so the `caId` in the path selects which kind
to rotate rather than which row is replaced.

> **Warning:** for the session and host CAs, "both trusted" must also be
> true on your nodes and clients: the `TrustedUserCAKeys` file and
> `@cert-authority` lines must contain the incoming key *before* the
> outgoing key drains. Re-export it as above and redistribute before you
> drain. The platform does not (and cannot) verify that your fleet's trust
> distribution has completed; sequence your config management accordingly,
> and don't rush the drain. This gap is a documented accepted risk: the
> platform trusts you to finish distribution.

For an emergency rotation after suspected CA compromise, pair it with a
[lock](locks.md): lock first (immediate, un-overridable), rotate second
(the durable fix). The lock is what protects you while trust distribution
catches up, which is the slow part.

## Signing availability is an SLO

The session CA gates every *new* session. Existing sessions continue if a
signer goes down, but nothing new starts, fail-closed. With the `local`
backend the signer's availability is the database's availability, so treat
them as one thing: the Control Plane exposes a health indicator and meters for
signing, and the shipped alerts page on signer fail-closed spikes. See
[Monitoring](../operations/monitoring.md).

## Next

- [Production hardening](../security/hardening.md): the KEK that protects
  whatever stays on `local`, and adopting Key Vault for the rest.
- [Nodes](nodes.md): the `TrustedUserCAKeys` line and host anchors this
  page's trust model relies on.
- [Locks](locks.md): the immediate revocation tool, so rotation never has
  to be one.
- [Trust model](../security/trust-model.md): the two-CA separation in the
  wider threat model.
