# Authentication

This guide explains how people and machines prove who they are — to the
Gateway when they SSH, and to the Control Plane's REST API when they
administer. When you're done you'll know the SSH method ladder, how pinning
makes reconnects silent, how to issue OTPs, and how to set up machine and
first-admin access.

## Prerequisites

- [ ] A configured OIDC identity provider (see
      [Install the Control Plane](../installation/control-plane.md)).
- [ ] For the admin API calls: a bearer token in `$TOKEN` — from your own
      OIDC login or a service account (see
      [Machine identities](#machine-identities)).

## The SSH method ladder

The Gateway advertises standard `publickey` and `keyboard-interactive`
authentication, and evaluates what the client offers in a fixed order:

1. **User certificate** — a short-lived certificate from the
   [user CA](certificate-authorities.md) (for example, Vault-issued).
2. **Pinned key** — a public key pinned to your identity by a previous login.
3. **Pre-issued OTP** — a one-time passcode, entered over
   keyboard-interactive.
4. **OIDC device flow** — browser sign-in at your IdP, as the fallback.

An expired or invalid credential degrades gracefully to the next method — it
never hard-fails the connection. The order is deliberate: certificate and key
methods are phishing-resistant and non-interactive, so they are primary;
the interactive device flow exists for first logins and browserless recovery,
not for every day.

Whatever method authenticates you, **authorization is always re-run** — no
method is a shortcut past [RBAC](rbac.md), and a [lock](locks.md) denies
regardless of credential validity.

## First login: the OIDC device flow

A user with no credential just runs `ssh`. The Gateway presents a
keyboard-interactive prompt carrying a verification URL and a short user
code; the user opens the URL in any browser (on any device — nothing calls
back to the SSH client's machine), signs in at the IdP, and confirms the
code. While the browser step is in flight, the Gateway keeps the SSH
connection alive with heartbeat prompts so stock clients don't time out.

Two properties matter for your threat model:

- The verification page is served by the Control Plane as a full
  authorization-code + PKCE OIDC relying party — with `state`, `nonce`, and
  PKCE — restoring the replay protections a raw device grant lacks.
- The approving browser's source context is recorded and correlated against
  the SSH source IP in the audit trail.

> **Warning:** device-flow phishing (an attacker initiates a flow and lures a
> victim into approving it) is an inherent residual of the OAuth device grant
> — this is why device flow is fallback-only. Strict *enforcement* of the
> approver-IP ↔ SSH-IP match is available but off by default (an exact match
> over-denies NAT and mobile approvers); enable it where your population
> allows, train users to check that the code they confirm matches the one in
> their terminal, and prefer certificate/key methods as the daily path.

ID tokens are validated strictly (signature against the IdP's JWKS with an
algorithm allow-list, `iss`, `aud`, `nonce`, expiry), and group claims map to
logins **server-side** — a user never picks an arbitrary Linux principal.

## Pinning: why the second login is silent

After a successful device-flow or OTP login, the Gateway pins the public key
the client offered: `{fingerprint, identity, source CIDR, allowed logins,
expiry}`. Reconnecting within the TTL from a matching source authenticates
silently as method 2 — no browser, no prompt. This is what makes `ssh` feel
normal day-to-day, and it also works with hardware-backed keys: an
`sk-ecdsa` FIDO2 key can be the pinned key, so possession of the hardware
token is what reconnects.

Pins are an authentication shortcut **only**:

- TTL is capped at the authorization TTL — a pin can never outlive the access
  that justified it.
- The source-CIDR binding is a deny-only reducer; connecting from elsewhere
  falls back to the interactive ladder rather than hard-failing.
- Every reconnect re-runs full authorization; pins live only in the Gateway's
  outer-leg verifier and are never trusted by any node.

Admins can list and revoke pins, and pins are revoked automatically on
offboarding, on a lock, and on OIDC back-channel logout where the IdP
supports it:

```bash
curl -s https://cp.example.com/v1/pins -H "Authorization: Bearer $TOKEN"

# PIN_ID is the id of the pin to revoke, from the list above.
curl -s -X DELETE https://cp.example.com/v1/pins/$PIN_ID \
  -H "Authorization: Bearer $TOKEN"
```

## Pre-issued OTPs

An OTP is a one-time passcode an admin issues for a specific identity —
useful for onboarding someone whose IdP account isn't live yet, or as a
controlled recovery path:

```bash
curl -s https://cp.example.com/v1/otp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "identity": "alice@example.com",
    "allowedPrincipals": ["deploy"],
    "sourceCidr": "203.0.113.0/24",
    "ttlSeconds": 300
  }'
```

The raw code is returned exactly once — deliver it out of band. Properties,
all enforced server-side: single use (atomic mark-used, replay rejected),
short TTL (60–300 seconds; default 120), at least 128 bits of entropy, stored
hashed, rate-limited, and the authenticated identity always comes from the
issuance record — never from anything the client types. The user enters it at
the keyboard-interactive prompt with echo off.

## Machine identities

Machines authenticate with OAuth **client-credentials** — no browser, no
device flow. Create a service account, issue it a credential, then exchange
it for short-lived bearer tokens:

```bash
curl -s https://cp.example.com/v1/service-accounts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: sa-deploy-bot-1" \
  -d '{ "name": "deploy-bot" }'

# SA_ID is the id from the response above. Prefer private_key_jwt or mTLS;
# publicKeyPem is the client's PUBLIC key — the private half never leaves it.
curl -s https://cp.example.com/v1/service-accounts/$SA_ID/credentials \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "credentialType": "private_key_jwt", "publicKeyPem": "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEexampleOnlyNotARealKey=\n-----END PUBLIC KEY-----" }'

curl -s https://cp.example.com/v1/oauth2/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=client_credentials" \
  --data-urlencode "client_id=deploy-bot" \
  --data-urlencode "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer" \
  --data-urlencode "client_assertion=$SIGNED_JWT"
```

`$SIGNED_JWT` is a JWT your client signs with its private key (RFC 7523) —
most OAuth libraries produce it directly. Three credential types exist:
`private_key_jwt` and `mtls` (preferred — no shared secret at rest) and
`client_secret` (accepted but discouraged; the raw secret is shown once).
Service accounts are first-class RBAC principals: bind them platform roles
like any user, and target them in data-plane rules for machine SSH.
Revocation is immediate for new sessions.

## REST API authentication schemes

The Control Plane API accepts exactly three first-class schemes:

| Scheme | Use |
|---|---|
| OIDC bearer JWT | humans (the Dashboard's tokens) |
| mTLS client certificate | platform components and pre-provisioned automation |
| OAuth client-credentials bearer | service accounts |

> **Warning:** HTTP Basic is **not** a first-class scheme and is off by
> default. It can be explicitly enabled only behind mTLS plus an IP
> allow-list as a narrow bootstrap escape hatch, and the server warns loudly
> at startup when it is. Treat it as a discouraged last resort, never a
> supported mode.

## First-admin bootstrap

A fresh install has empty RBAC, and default-deny would lock everyone out. The
one-time bootstrap resolves this in one of two ways:

- **Config-named subject** — set `sessionlayer.bootstrap.admin-subject` to an
  OIDC subject (and `sessionlayer.bootstrap.admin-subject-kind` to `user` or
  `group`); that subject is provisioned as the initial platform admin at
  startup.
- **Printed-once credential** — with no subject configured, the Control Plane
  generates a bootstrap credential, prints it exactly once to its log, and
  provisions whoever first presents it.

Either way, the bootstrap path **self-disables** as soon as a platform admin
exists, and its use is audited. If you use the printed-once path, claim it
promptly and treat the log line as a secret.

## Next

- [RBAC](rbac.md) — what an authenticated identity may actually do.
- [Break-glass access](break-glass.md) — the IdP-independent emergency path.
- [SSH access](../user-guide/ssh-access.md) — the user's view of these
  methods.
- [Production hardening](../security/hardening.md) — the auth-related
  preconditions before go-live.
