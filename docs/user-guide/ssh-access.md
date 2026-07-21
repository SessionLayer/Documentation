# SSH access

You connect to nodes through SessionLayer with the stock OpenSSH client you
already have — `ssh`, `sftp`, `scp`, `~/.ssh/config`, `ProxyJump`, and
connection multiplexing all work. This page shows the three ways to address a
node, what the authentication prompts look like, and what to expect when access
is refused. Every command here runs against the
[quickstart](../getting-started/quickstart.md) stack.

Prerequisites:

- [ ] The quickstart stack is running and you completed it (your client
      container has a pinned key for `alice@example.com`).
- [ ] Commands run from the `examples/quickstart` directory; `curl` and `jq`
      for the OTP section.

## How addressing works

The Gateway is a single SSH front door for the whole fleet, and stock `ssh`
gives a server exactly one place to carry extra information: the username. So
SessionLayer needs two things from your connection — the Linux login and the
target node — and offers three ways to say them:

| Mode | You type | How the node travels |
|---|---|---|
| Username encoding | `ssh deploy%web-01@gw.example.com` | inside the username |
| Wildcard DNS | `ssh deploy%web-01.nodes.example.com@…` | inside the username; the Gateway strips the DNS suffix |
| ProxyJump | `ssh -J gw.example.com deploy@web-01` | as the jump target — a natural `user@node` |

In every mode the node *name* is resolved to a node by the Control Plane,
server-side. An unknown or unauthorized name gets the same generic denial —
the Gateway never discloses whether a node exists.

## Username encoding

The baseline: `login%node` as the username, aimed at the Gateway. The
separator is `%` (operator-configurable), with exactly one separator and both
halves non-empty:

```bash
docker compose exec -T client ssh -p 2222 -o StrictHostKeyChecking=accept-new \
  deploy%web-01@gateway 'hostname'
```

Typing the encoding every time gets old, so give each node a `~/.ssh/config`
block — after this, plain `ssh web-01` works:

```bash
docker compose exec -T client sh -c 'mkdir -p /root/.ssh && cat >> /root/.ssh/config <<EOF
Host web-01
  HostName gateway
  Port 2222
  User deploy%%web-01
  StrictHostKeyChecking accept-new
EOF'
docker compose exec -T client ssh web-01 'hostname'
```

> **Note:** inside `~/.ssh/config`, `%` is OpenSSH's expansion character, so
> the `User` value writes the separator as `%%` (a literal `deploy%web-01` —
> if you see `percent_expand: unknown key`, this is why). The line must spell
> out the full encoding per node: OpenSSH has no expansion that builds it from
> the hostname, and a `user@` on the command line overrides the config's
> `User`. For a fully natural `ssh user@node` with nothing per-node, use
> ProxyJump below.

## Wildcard DNS

Operators can point a wildcard DNS zone (say `*.nodes.example.com`) at the
Gateway, so every node hostname resolves to the front door with no per-node
DNS. The node still travels in the username — but the Gateway strips the
configured suffix, so fully-qualified names work naturally:

```bash
docker compose exec -T client ssh -p 2222 -o StrictHostKeyChecking=accept-new \
  deploy%web-01.nodes.example.com@gateway 'hostname'
```

`web-01.nodes.example.com` became `web-01` before authorization. Matching is
case-insensitive, the longest configured suffix wins, and a name that matches
no suffix passes through unchanged — so both spellings work side by side. Many
teams ship a one-line wrapper so users type `sl-ssh deploy@web-01.nodes.example.com`:

```sh
sl-ssh() { local u=${1%@*} h=${1#*@}; shift; ssh "${u}%${h}@gw.example.com" "$@"; }
```

## ProxyJump: natural `user@node`, cryptographically verified

`ssh -J <gateway> deploy@web-01` gives the natural form: the node travels as
the SSH jump target, not in the username. The Gateway terminates the jump's
inner hop and presents a **host certificate for `web-01`**, signed by the
platform's host CA — so your client verifies the Gateway *as* the node. This
is a deliberate, cryptographically explicit man-in-the-middle: it is what
makes the session recordable, and it is verified, never trust-on-first-use.

Your one-time setup is a single `@cert-authority` line in `known_hosts` (your
operator distributes the host CA public key; the quickstart seed leaves it in
`/state/host_ca.pub`):

```bash
docker compose exec -T client sh -c \
  'echo "@cert-authority web-01 $(cat /state/host_ca.pub)" >> /root/.ssh/known_hosts'
docker compose exec -T client sh -c 'cat >> /root/.ssh/config <<EOF
Host jump
  HostName gateway
  Port 2222
  User deploy
  StrictHostKeyChecking accept-new

Host web-01.direct
  HostName web-01
  User deploy
  ProxyJump jump
  StrictHostKeyChecking yes
EOF'
docker compose exec -T client ssh web-01.direct 'hostname'
```

Note `StrictHostKeyChecking yes` on the target: the `@cert-authority` line is
sufficient to verify it, with no prompt and no first-use leap of faith. Scope
the `@cert-authority` pattern to your node namespace (`*.nodes.example.com`,
or explicit names) rather than `*`.

> **Warning:** if a client disables host-key checking on the target hop, it
> gives up the no-TOFU guarantee — that is client misconfiguration, not a
> platform mode. Keep the target strict; only the jump hop may be `accept-new`.
> Agent forwarding is always refused on the ProxyJump path, and only one hop is
> allowed — a second nested jump is refused.

## How authentication looks

The Gateway advertises `publickey` and `keyboard-interactive` and tries, in
order: a user certificate, a pinned public key, a pre-issued one-time passcode
(OTP), then the OIDC device flow. An expired credential quietly falls through
to the next method — you re-authenticate, you don't get locked out.

- **Certificate or pinned key:** nothing to see — `ssh` authenticates silently,
  like any key-based login. This is what the quickstart commands above use.
- **One-time passcode:** an admin issues you a short-lived, single-use code
  (60–300 seconds), delivered out of band. Issue one now (in production an
  admin runs this and hands you the code):

  ```bash
  TOKEN=$(curl -s http://127.0.0.1:8080/v1/oauth2/token -H 'Content-Type: application/json' \
    -d '{"grant_type":"client_credentials","client_id":"quickstart-admin","client_secret":"quickstart-admin-dev-secret"}' | jq -r .access_token)
  curl -s -X POST http://127.0.0.1:8080/v1/otp -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"identity":"alice@example.com","allowedPrincipals":["deploy"],"ttlSeconds":300}' | jq '{otp, expiresAt}'
  ```

  Connecting with no usable key, you're prompted (input hidden):

  ```text
  $ ssh deploy%web-01@gw.example.com
  SessionLayer
  Enter a one-time passcode, or press Enter to log in via your browser.
  (deploy%web-01@gw.example.com) One-time passcode:
  deploy@web-01:~$
  ```

  After an OTP (or device-flow) success the Gateway *pins* the public key your
  client offered, for a bounded TTL: reconnects within it authenticate
  silently, from the same source network. The pin is an authentication
  shortcut only — every new connection still runs full authorization.
- **OIDC device flow (fallback):** with nothing else to offer, the prompt
  shows a verification URL and a short code. Open the URL in any browser (any
  device — your laptop needs no browser), sign in to your identity provider,
  and match the code; the connection completes by itself. The Gateway sends
  quiet keep-alives while you do, so your client won't time out. If you take
  too long: `authentication timed out, please reconnect` — just retry.

## Multiplexed connections (ControlMaster)

`ControlMaster` reuses one authenticated connection for many commands — useful
with tools that open lots of sessions. SessionLayer treats the multiplexed
connection as one authentication but authorizes **every new channel**: each
one re-checks capabilities, grant expiry, and locks locally on the Gateway.

```bash
docker compose exec -T client ssh -o ControlMaster=auto \
  -o ControlPath=/tmp/cm-%C -o ControlPersist=60 web-01 'true'
docker compose exec -T client ssh -o ControlPath=/tmp/cm-%C web-01 'echo multiplexed'
```

The second command rides the first connection — no new authentication. If your
grant expires or a lock lands mid-connection, new channels are refused and
matching live channels are torn down, even though the connection authenticated
hours ago.

## What "denied" looks like

Refusals before authorization are deliberately generic — they never reveal
whether an identity, node, or rule exists. After authorization, operational
errors may be specific (you're already entitled to know the target exists).

| You see | It means | Do |
|---|---|---|
| connection dropped before any SSH banner | your source IP is outside the operator's allow-list | connect from an approved network |
| standard SSH authentication failure | no method succeeded | check your key/OTP; ask your admin |
| `access denied by policy` | authenticated, but no rule allows this login on this node — or a lock is in force | request access ([JIT](requesting-access.md)) or ask your admin |
| `authentication timed out, please reconnect` | the device-flow window lapsed | reconnect and finish the browser step promptly |
| `the target node is offline or unavailable` | you're authorized, but the node can't be reached or failed host verification | tell your operator |
| `session cannot start: recording unavailable` | strict recording is on and the recorder can't start | tell your operator |
| `service temporarily unavailable` | the Control Plane is unreachable — new sessions fail closed | retry; tell your operator |

A lock and an RBAC deny look identical from `ssh` — by design. The specific
reason is in the audit trail for your admin, not on your terminal.

## Next

- [File transfer](file-transfer.md) — SFTP and SCP through the platform.
- [Requesting access](requesting-access.md) — JIT access when you need more than you have.
- [Core concepts](../getting-started/concepts.md) — why sessions work this way.
- [Nodes](../admin-guides/nodes.md) — the admin's view of addressing and enrollment.
