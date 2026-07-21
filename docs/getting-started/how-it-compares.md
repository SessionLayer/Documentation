# How SessionLayer compares

This page positions SessionLayer against the approaches teams usually consider,
and states plainly what it does not do. Every claim here is backed by the
platform's code and proof suite; the omissions are as deliberate as the
features.

## What SessionLayer is

- **SSH access for a Linux fleet, from stock OpenSSH clients.** No custom
  client, no wrapper binary required: `ssh`, `sftp`, `scp`, `ProxyJump`, and
  `~/.ssh/config` work as-is. The platform's client-side footprint can be as
  small as one `known_hosts` line.
- **A terminating, recording proxy.** The Gateway decrypts and re-encrypts
  every session — that is what makes session recording, keystroke capture, and
  file-transfer audit possible, and it is stated up front rather than implied
  away (see [Core concepts](concepts.md)).
- **Recording your vendor cannot read.** Recordings are sealed to a key pair
  whose private half only you hold. This matters *because* the platform is
  self-hosted: even your own platform admins, a compromised Control Plane, or
  anyone with raw object-store access get ciphertext. Decryption happens
  client-side (in the Dashboard's player, or offline with your own tooling).
- **Short-lived certificates everywhere.** No standing SSH keys in the access
  path; nodes trust exactly one CA line; every session mints a fresh
  certificate after a fresh policy decision.
- **Self-hosted and open.** GPL-3.0, your infrastructure, your Postgres, your
  object store, your identity provider. There is no SaaS control plane and no
  phone-home.
- **Operable in two sizes.** A single-instance mode whose only dependency is
  Postgres, and an opt-in HA mode (multiple Control Planes and Gateways,
  gateway-to-gateway relay) when you need it.

## What SessionLayer deliberately does not do

- **Anything other than SSH.** No Kubernetes API access, no database access, no
  RDP, no HTTP application proxying, no VPN. Teleport-style platforms cover
  those surfaces; SessionLayer covers one protocol and aims to cover it to the
  bottom (protocol-decoded SFTP/SCP audit, per-channel authorization,
  cert-verified hosts).
- **An end-to-end-encrypted mode.** Some platforms offer a mode where the proxy
  cannot see session content. SessionLayer's recording guarantees depend on
  seeing the plaintext at the Gateway, so it does not offer one. If a
  plaintext-visible intermediary is unacceptable in your threat model, use
  plain SSH — the [trust model](../security/trust-model.md) spells out this
  trade-off.
- **GitOps configuration sync.** Configuration is managed through the API, the
  Dashboard, or your own automation against the API. A built-in Git
  reconciler is not part of the platform today.
- **Session migration across Gateway failures.** A session whose bytes transit
  a failed Gateway terminates (fail-closed) and you reconnect; surviving
  Gateways keep serving. Live SSH crypto state is not replicated — reconnection
  is cheap by design (pinned keys re-authenticate silently).
- **Trust-on-first-use, anywhere.** If a host identity cannot be verified
  against enrolled material, the connection fails. There is no "accept and
  remember" fallback to misconfigure.

## Against the usual alternatives

**A bastion / jump host.** A classic bastion forwards ciphertext, so it gives
you a choke point but no recording, no command audit, and no per-session
authorization — and it usually accumulates the fleet's authorized_keys sprawl.
SessionLayer is the same topology (one front door) with a decision point,
per-session certificates, and recording at that choke point.

**DIY SSH certificates (a CA + configuration management).** SSH CAs solve key
sprawl, and if that is your whole problem, a CA plus automation is a fine
answer. What you build on top over time — short TTLs, an approval workflow,
revocation that actually tears down live sessions, recording, file-transfer
audit, an audit trail correlating approval → session → replay — is roughly this
platform. SessionLayer is that layer, pre-built and tested.

**Teleport-style access platforms.** The closest category, and the right
choice if you need multi-protocol access (Kubernetes, databases, web apps) in
one product. Choose SessionLayer when your surface is SSH and you weight
self-hosting, recordings your platform operators provably cannot read,
stock-client ergonomics, and a small, auditable deployment (three components,
Postgres, an object store).

**A VPN + plain SSH.** A VPN authorizes network reachability, not sessions: it
answers "may this laptop reach the subnet", not "may this person be `deploy` on
`web-01` right now, recorded". The two compose — SessionLayer commonly runs
behind a VPN, adding the per-session decision and the evidence trail.

## The honest cost

You are inserting a Tier-0 component into your access path. The Gateway sees
session plaintext and its CAs can mint access to any enrolled node — that is
inherent to what a recording proxy is, and it is why the platform ships a
[hardening runbook](../security/hardening.md) (privilege drop, seccomp,
Landlock, read-only rootfs, egress confinement), a
[supply-chain verification path](../security/supply-chain.md) (signed,
reproducible releases; the Agent verifies before it runs), and a
[trust model](../security/trust-model.md) that names its accepted risks instead
of hiding them. Evaluate that page as critically as this one.

## Next

- [Quickstart](quickstart.md) — judge it running, not on paper.
- [Core concepts](concepts.md) — the architecture behind these claims.
- [Trust model](../security/trust-model.md) — what the platform can and cannot protect against.
