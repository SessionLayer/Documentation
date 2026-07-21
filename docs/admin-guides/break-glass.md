# Break-glass access

Break-glass is the **always-available emergency path**: when your identity
provider is down at 3am and production is on fire, a registered hardware key
or a pre-issued offline code still gets an operator in — loudly. This guide
shows you how to provision both credential types, what a break-glass session
forces, and how to run the review that every use requires.

Break-glass is deliberately *not* "JIT with zero approvers". It is a distinct
path with its own credentials, and every use:

- fires a **high-priority alert** the moment the credential authenticates —
  even if no session follows;
- **forces strict recording** — if the recording cannot start or fails
  mid-session, the session dies;
- creates a durable activation that **requires post-hoc review**;
- is **time-boxed** (default 1 hour) and **cannot override a
  [lock](locks.md)** — deny still wins.

## Prerequisites

- The `breakglass:manage` platform permission for provisioning; a bearer
  token in `$TOKEN` ([Authentication](authentication.md)).
- One or more FIDO2 hardware keys (the primary path).
- A configured alert target ([break-glass policy](#the-break-glass-policy)).

## Provision FIDO2 keys (primary)

Generate an `sk-ecdsa` key on the operator's hardware token:

```bash
ssh-keygen -t ecdsa-sk -f ~/.ssh/breakglass_sk -C "breakglass alice@example.com"
```

> **Warning:** the key MUST require a physical touch — never pass
> `-O no-touch-required`. The Gateway's SSH library verifies *possession* of
> the hardware key but cannot assert the touch (user-presence) flag
> server-side; touch is enforced by the authenticator itself. A
> touch-required key is therefore an operator precondition, not a default you
> get for free — a no-touch key would let malware on the operator's machine
> use the token silently. This is a documented accepted risk (BG-1) in the
> [trust model](../security/trust-model.md). Only `ecdsa-sk` keys work;
> an `ed25519-sk` key is routed to the ordinary pin path, with an operator
> log line telling you why.

Register the **public** half — the second field of the `.pub` file is the
key blob the API wants:

```bash
curl -s https://cp.example.com/v1/breakglass/credentials \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "publicKey": "'$(awk '{print $2}' ~/.ssh/breakglass_sk.pub)'",
    "identity": "alice@example.com",
    "allowedPrincipals": ["root", "deploy"]
  }'
```

Scope a credential to specific nodes with `nodeIds` if the operator's
emergency remit is bounded; omit it for a fleet credential. Registration
stores public material only — an attacker who dumps the credential table
holds nothing that can authenticate.

> **Warning:** never register the same key as both an everyday pinned key and
> a break-glass credential. A routine login with it would fire the
> high-priority alert and force strict recording every time.

## Issue offline codes (fallback)

Offline codes cover the operator whose hardware key is lost or unreadable:

```bash
curl -s https://cp.example.com/v1/breakglass/offline-codes \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "identity": "alice@example.com",
    "allowedPrincipals": ["root"],
    "count": 10,
    "ttlSeconds": 7776000
  }'
```

The raw codes are returned exactly once (defaults: 10 per batch, 90-day
lifetime) — print them and store them in a physical safe, per operator. Each
code is single-use with atomic consumption, stored only as a hash, at least
128 bits of entropy, optionally source-CIDR-bound, and rate-limited per
source.

> **Warning:** codes are entered echo-off at the SSH keyboard-interactive
> prompt. Never place a code in an environment variable, a script, or a
> password manager's autotype in production — a pre-staged code is a standing
> credential, which is exactly what break-glass exists to avoid.

## Using it

The operator connects like any other session — `ssh` to the Gateway, offering
the `sk` key (or entering a code at the prompt). Resolution happens against
the Control Plane over its own mTLS plane, **independent of the OIDC IdP**:
a dead or compromised IdP does not take break-glass down with it.

What happens next, in order: the alert fires and a pending activation is
recorded (at authentication, before any session); authorization runs — and a
matching lock still denies, with the activation and alert standing as
evidence of the attempt; the session starts strictly recorded, time-boxed to
the policy TTL with grace-then-kill expiry.

> **Warning:** "recording could not start" kills a break-glass session by
> design — the message is `session cannot start: recording unavailable`. If
> that fires during a real incident, the recording backend (customer key
> configured, WORM store reachable) is your first repair target — see the
> [Gateway runbook](../operations/gateway-runbook.md). Likewise, a Gateway
> whose lock feed is unhealthy refuses break-glass channels: it cannot
> confirm the absence of a lock, and deny fails closed.

Break-glass is exempt from [session limits](session-limits.md) — an emergency
is never queued behind a concurrency cap.

## The break-glass policy

`POST /v1/breakglass-policies` configures the behavior knobs: `alertTarget`
(where the high-priority alert goes), `recordingStrict`, `reviewRequired`,
and the preferred `authPath`. The default alert transport is a loud audit
event plus an ERROR log — wire `alertTarget` into your paging pipeline via
your [SIEM forwarder](audit.md) so a 3am activation actually wakes someone.

## Review every activation

Every activation stays `pending` until a human reviews it:

```bash
curl -s https://cp.example.com/v1/breakglass/activations \
  -H "Authorization: Bearer $TOKEN"

# ACTIVATION_ID is the id of the pending activation from the list above.
curl -s https://cp.example.com/v1/breakglass/activations/$ACTIVATION_ID/review \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "note": "Legitimate use during IR-1234; recording replayed and consistent." }'
```

Treat an activation unreviewed after 72 hours as a standing signal in your
alerting. A review should confirm the *who/why*, and replay the (forced)
[recording](session-recording.md) of what was done.

## Run drills

An emergency path you have never exercised is a path that fails during the
emergency. Quarterly, per operator: use the registered key against a
designated drill node, then confirm the whole chain — the alert reached the
pager, the activation appeared and was reviewed, the strict recording exists
and replays. Rotate any operator's offline-code batch that the drill consumed.

## The honest limits

Break-glass depends on the Control Plane and a Gateway being reachable — it
is an *authorization override*, not an infrastructure bypass. If the platform
itself is down, the recovery path is the one SessionLayer deliberately never
takes away: your own native SSH keys or console/serial access to the node
(the platform never modifies the node's `sshd` beyond one trust line). And a
lock beats break-glass everywhere, always — there is no credential in the
system that outranks a deny.

## Next

- [Locks](locks.md) — the one thing break-glass cannot beat.
- [Session recording](session-recording.md) — the strict recording it forces.
- [Trust model](../security/trust-model.md) — BG-1 and the other accepted
  risks, in plain language.
- [Gateway runbook](../operations/gateway-runbook.md) — break-glass log
  reasons and their fixes.
