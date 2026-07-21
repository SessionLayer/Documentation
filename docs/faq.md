# FAQ

Short, honest answers. Where a question deserves depth, the answer links to
the page that has it.

## Can SessionLayer staff or a platform admin read my recordings?

**No.** Recordings are encrypted, before upload, to a public key whose
private half only you (the operator) hold — the platform stores the public
half and ciphertext, and replay decrypts in your browser with a key that
never leaves it. There is no platform-side decryption path: a platform
admin, a compromised Control Plane, or SessionLayer's developers can read
recording *metadata*, never content. This is tested directly (a reader
holding everything the platform holds cannot decrypt), not just promised.
See [Session recording](admin-guides/session-recording.md).

## Is this really "zero trust" if it man-in-the-middles my SSH?

Fair question — and answered honestly rather than papered over. Zero trust
here is the access-decision model: no implicit network trust, every session
re-authorized, all credentials short-lived. The Gateway *is* a fully-trusted
intercepting proxy — that's what makes recording and file-transfer audit
physically possible — so the platform **relocates** trust from long-lived
keys scattered everywhere into one audited, hardened control point; it does
not eliminate trust. If your threat model rejects any plaintext-visible
intermediary, use end-to-end SSH and accept losing recording/audit. See the
[Trust model](security/trust-model.md).

## Does it support Kubernetes, databases, RDP, or web apps?

**No. SessionLayer is SSH-only**, for a fleet of Linux nodes, from stock
OpenSSH clients. There is no kubectl proxying, database access, or
application gateway, and none is documented here because none exists. See
[How SessionLayer compares](getting-started/how-it-compares.md).

## What happens when the Control Plane is down?

Existing sessions keep running — their bytes flow Gateway ↔ node directly —
while **new** sessions fail closed with "service temporarily unavailable".
Locks keep working (they're pushed to Gateways ahead of time, precisely so
revocation survives a datastore loss), and a Gateway that can't verify its
deny-list refuses rather than guesses. Your own native SSH keys and console
access remain valid independent recovery paths — the platform never touches
a node's `sshd` beyond one added trust line. See
[Troubleshooting](operations/troubleshooting.md).

## Can I keep using my existing SSH keys?

For *reaching the Gateway*, mostly yes: after your first login, the key your
client offered is pinned to your identity and reconnects silently (hardware
`sk` keys included). What you cannot do is use a long-lived key as a
standing path **to a node** — nodes trust only the platform's session CA,
and every session gets a fresh short-lived certificate minted after policy
passes. A refused bare-key login against a node is the design working. See
[Authentication](admin-guides/authentication.md).

## Do users need to install anything?

No. Stock OpenSSH is the supported client — `ssh`, `sftp`, `scp`, ProxyJump,
`ControlMaster` all work. Setup is a few lines of `~/.ssh/config` (or a
one-line shell alias) depending on the addressing mode. See
[SSH access](user-guide/ssh-access.md).

## Do I need an agent on every node?

No. Agentless nodes need only stock `sshd` plus one `TrustedUserCAKeys` line
— the Gateway dials them directly. The [Agent](admin-guides/nodes.md) exists
for nodes without inbound reachability (NAT, strict firewalls): it dials
out, so the node needs zero open ports, and it adds a node-local second
audit trail. A fleet can mix both models.

## Can I manage configuration via GitOps?

**Not in this release.** A Git reconciler was designed but descoped by
decision — the two related requirements are the only unimplemented rows in
the production sign-off, recorded as gaps rather than quietly dropped.
Everything is manageable via the [REST API](reference/api.md) (which your
own pipeline can drive) and the Dashboard. Nothing in these docs describes a
GitOps flow, because none exists.

## Can a session survive a Gateway restart or failure?

No — there is no live SSH session migration (two live SSH crypto states
can't be moved), and no such feature is planned around the edges of physics.
The design instead makes reconnection cheap (pinned-key silent reconnect)
and failure bounded: planned restarts drain gracefully, and in HA the rest
of the fleet keeps serving while ownership fails over. See
[High availability](admin-guides/high-availability.md).

## Could an admin alter or delete a recording to cover their tracks?

Recordings and audit events are hash-chained and stored under S3 object
lock; altering, truncating, or reordering breaks the chain, and in
compliance mode nobody — including the platform — can delete before
retention expires. Replay/export/delete are themselves audited. The honest
limit: without the (deferred) external Merkle anchor, a full database
superuser who also defeats the append-only trigger could rewrite the *audit*
chain at the source — which is why the off-box SIEM forward and the
restricted DB role are go-live preconditions. See the
[Trust model](security/trust-model.md).

## What if I lose the customer recording key?

Every recording becomes permanently unreadable — by everyone, including you.
The platform cannot help, by construction (that same property is why it
can't read your recordings). Store the private key like the crown jewel it
is. See [Production hardening](security/hardening.md).

## Can break-glass get around a lock?

No. A lock is the top-tier deny: no standing rule, JIT approval, or
break-glass credential overrides it, in any degraded state. Break-glass
bypasses *approval chains and the IdP*, never denial — and every use alarms,
forces strict recording, and requires review. See
[Break-glass access](admin-guides/break-glass.md).

## Is my session data sent to SessionLayer (the project) or any third party?

No. SessionLayer is fully self-hosted — Control Plane, Gateways, recordings,
and audit all live in your infrastructure, and the components phone home to
nothing. The only outbound trust relationship is the one *you* configure for
verifying release signatures (a pinned Sigstore trust root, checked
offline). See [Supply chain](security/supply-chain.md).

## Next

- [Quickstart](getting-started/quickstart.md) — see it run in ~20 minutes.
- [Core concepts](getting-started/concepts.md) — the vocabulary behind these
  answers.
- [Trust model](security/trust-model.md) — the long-form honesty page.
