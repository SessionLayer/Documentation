# Quickstart

In about 20 minutes of hands-on time you will stand up a complete SessionLayer
deployment on your machine, make your first SSH connection through it from a
stock OpenSSH client, watch the session get recorded and audited, and decrypt
the recording locally with a key the platform itself does not hold.

Everything runs in Docker containers — including the SSH client — so nothing
here touches your own SSH configuration. The stack is a real one: the actual
Control Plane and Gateway built from source, Postgres, a write-once (WORM)
object store (MinIO), one node running plain OpenSSH, and the platform's real
REST API for every step.

## Prerequisites

- [ ] Docker Engine with a current Docker Compose v2 (tested with Docker 29 /
      Compose v5; the stack uses `additional_contexts`, so Compose v2.24+ is
      required), on x86_64 or aarch64 Linux. macOS with Docker Desktop is
      expected to work but is untested.
- [ ] `curl` and `jq`.
- [ ] About 10 GB of free disk during the first build and 4 GB of free RAM;
      internet access (the build pulls from GitHub and public registries).
- [ ] One shell session for all steps — later commands reuse variables set by
      earlier ones.

> **Note:** the first `docker compose up` compiles the Control Plane (Java)
> and the Gateway (Rust) from source — from the **tip of each repository's
> `main` branch**, unpinned. That is an evaluation convenience, not an
> installation practice: production installs verify signed releases instead
> (see [Supply chain](../security/supply-chain.md)). The build is roughly
> 30–50 minutes of unattended time on a small (2-core) machine — faster with
> more cores — and the 20 minutes of *your* attention starts after it.
> Subsequent starts reuse the images and take seconds.

## 1. Start the stack

```bash
git clone https://github.com/SessionLayer/Documentation.git
cd Documentation/examples/quickstart
docker compose up -d --wait
```

> **Tip:** if the first `up -d --wait` fails with a transient Docker error,
> run it again — every service, including the seed, is safe to re-run.

Compose builds and starts seven containers: `postgres`, `minio`,
`controlplane`, `gateway`, one node (`web-01`), a `client` (your stand-in
workstation), and a one-shot `seed`. The seed provisions exactly the four
things that have no API surface, and says so in its log: the CA trust anchors
(the Gateway's mTLS anchor, the session CA line the node trusts, the host CA
public key), a single-use Gateway enrollment token, the `quickstart-admin`
service account, and a demo **customer recording key** — the Control Plane
gets only its public half; the private half stays on a dedicated local volume
that only the decrypt tool mounts. Everything else you are about to do uses
the product's REST API.

> **Warning:** this stack deliberately relaxes three things for a throwaway
> evaluation: the Control Plane's local CA runs with a dev-only KEK
> (`SESSIONLAYER_CA_LOCAL_ALLOW_DEV_KEK=true` in `compose.yaml`), the
> credentials are fixed dev placeholders, and the Gateway's recorder uploads
> to the in-network plain-HTTP MinIO with `require_https: false` in its
> rendered config. Everything binds to `127.0.0.1`. All three are wrong for
> production, where CA keys live in a KMS/Key Vault/Vault backend,
> credentials are real, and the recorder keeps its HTTPS default — see
> [Production hardening](../security/hardening.md).

Wait for the Gateway to finish enrolling with the Control Plane and open its
SSH front door:

```bash
until docker compose logs gateway | grep -q "outer SSH leg listening"; do sleep 2; done
docker compose logs gateway | grep "outer SSH leg listening"
```

## 2. Claim the first admin

A fresh Control Plane has no users and default-deny everything — so who
creates the first admin? On first boot it prints a one-time bootstrap
credential to its log; whoever surrenders it becomes the first platform admin,
and the bootstrap self-disables. Fish it out and claim it:

```bash
until docker compose logs controlplane | grep -q "FIRST-ADMIN BOOTSTRAP CREDENTIAL"; do sleep 2; done
BOOT_CRED=$(docker compose logs controlplane | sed -n 's/.*FIRST-ADMIN BOOTSTRAP CREDENTIAL (shown once): \([A-Za-z0-9_-]*\).*/\1/p' | head -1)
curl -s http://127.0.0.1:8080/v1/bootstrap/claim -H 'Content-Type: application/json' \
  -d "{\"credential\":\"$BOOT_CRED\",\"subject\":\"quickstart-admin\"}"
```

You should see `{"status":"provisioned"}` — `quickstart-admin` is now platform
admin, the claim is audited, and this endpoint is dead from here on.

> **Warning:** the credential is printed once and only its hash is stored. In
> a real install, claim it immediately and treat the log line as a secret.

Mint an API token for the admin (the platform's OAuth client-credentials flow;
tokens live five minutes, so re-run this line whenever a later call answers
401 — the longer steps below re-mint it for you):

```bash
TOKEN=$(curl -s http://127.0.0.1:8080/v1/oauth2/token -H 'Content-Type: application/json' \
  -d '{"grant_type":"client_credentials","client_id":"quickstart-admin","client_secret":"quickstart-admin-dev-secret"}' | jq -r .access_token)
```

## 3. Enroll the node

`web-01` is a plain Debian container running stock `sshd` — SessionLayer
installs nothing on it. Enrolling an agentless node means telling the Control
Plane its dial address and its host identity. The platform's own connections
never trust a host on first use: the Gateway accepts only the host identity
you enroll, so you fetch the node's host key from the node yourself and pin
it here:

```bash
HOSTKEY=$(docker compose exec -T web-01 cat /etc/ssh/ssh_host_ed25519_key.pub | awk '{print $1" "$2}')
NODE_ID=$(curl -s -X POST http://127.0.0.1:8080/v1/nodes \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"name\":\"web-01\",\"address\":\"web-01:22\",\"labels\":{\"env\":\"quickstart\"},\"pinnedHostKey\":\"$HOSTKEY\"}" | jq -r .id)
echo "node registered: $NODE_ID"
```

If the key you pin here ever differs from what the node presents, the Gateway
aborts the session — that is the no-TOFU guarantee doing its job.

## 4. Grant access

Access is default-deny: right now, nobody can reach `web-01`. Write the first
data-plane rule — `alice@example.com` may be `deploy` on quickstart-labeled
nodes, including file transfer:

```bash
curl -s -X POST http://127.0.0.1:8080/v1/rules \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"quickstart-allow","identitySelector":{"identities":["alice@example.com"]},
       "nodeLabelSelector":{"env":{"op":"eq","value":"quickstart"}},
       "principals":["deploy"],"ttlSeconds":3600,
       "capabilities":["shell","exec","sftp","scp"],"effect":"allow"}' | jq '{name, effect, principals}'
```

Capabilities are opt-in per rule (the default is shell and exec only) and
deny-overrides: no combination of rules can widen what another rule denied.

## 5. Give Alice a key

Generate an SSH key in the client container and *pin* it to Alice's identity —
a pin is an authentication shortcut with a TTL, the same thing the platform
creates automatically after an OTP or device-flow login:

```bash
docker compose exec -T client sh -c 'mkdir -p /root/.ssh && ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519 -q'
FP=$(docker compose exec -T client ssh-keygen -lf /root/.ssh/id_ed25519.pub | awk '{print $2}')
curl -s -X POST http://127.0.0.1:8080/v1/pins \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"fingerprint\":\"$FP\",\"identity\":\"alice@example.com\",\"principals\":[\"deploy\",\"dba\"],\"ttlSeconds\":3600}" | jq '{identity, expiresAt}'
```

The pin's `principals` are the Linux logins this credential may *ask for* —
being able to ask is not being allowed. Note also what you did *not* do: put a
key on the node. The node trusts only the platform's session CA; Alice's key
authenticates her to the Gateway, and a fresh five-minute certificate is
minted per connection — only after the rule you just wrote says yes.

## 6. Your first session

```bash
docker compose exec -T client ssh -p 2222 -o StrictHostKeyChecking=accept-new \
  deploy%web-01@gateway 'echo hello from $(hostname); id -un'
```

That's a stock `ssh` client addressing node `web-01` as login `deploy` through
the Gateway (the `login%node` username encoding — the
[SSH access guide](../user-guide/ssh-access.md) shows two more addressing
modes, including natural `user@node` via ProxyJump). Behind the one command:
a source-IP gate, pin authentication, a signed authorization decision, a
fresh [inner certificate](concepts.md) (the Gateway's own short-lived
certificate toward the node), host-key verification against your pin, and a
recorder on the bridged session. Run the same command without the trailing
`'echo …'` for an interactive shell — everything you type is part of the
recorded session.

> **Note:** `accept-new` here trusts the Gateway's host key on first contact —
> fine for this throwaway loopback stack. Production clients pre-provision
> the Gateway's host key and connect strictly; the
> [SSH access guide](../user-guide/ssh-access.md) shows exactly that against
> this stack.

Deny is just as real. `dba` is a valid login on the node, but no rule grants
it, so:

```bash
docker compose exec -T client ssh -p 2222 -o StrictHostKeyChecking=accept-new \
  dba%web-01@gateway 'true' || echo "denied, as it should be"
```

The client sees only a generic denial — whether the cause is a missing rule, a
lock, or a nonexistent node is deliberately not disclosed at the SSH surface.

## 7. See the audit trail

Every step you took — the bootstrap claim, the node enrollment, the rule, the
pin, both connection attempts — is already in one correlated audit stream.
Pull the session's own trail:

```bash
TOKEN=$(curl -s http://127.0.0.1:8080/v1/oauth2/token -H 'Content-Type: application/json' \
  -d '{"grant_type":"client_credentials","client_id":"quickstart-admin","client_secret":"quickstart-admin-dev-secret"}' | jq -r .access_token)
SESSION=$(curl -s "http://127.0.0.1:8080/v1/sessions" -H "Authorization: Bearer $TOKEN" \
  | jq -r '.items | sort_by(.startedAt) | last | .id')
curl -s "http://127.0.0.1:8080/v1/audit-events?correlationId=$SESSION" \
  -H "Authorization: Bearer $TOKEN" | jq '.items[] | {action, actor, outcome}'
```

You get the authorization decision plus the recording lifecycle, correlated by
session id. Entries acted by the platform itself carry its component identity
as the actor — the bare UUID on `authz.decision` and `session.end` is the
Gateway's own enrolled identity. The same API searches by identity, node
label, source IP, capability, and
[access model](concepts.md) — see [Audit](../admin-guides/audit.md).

## 8. Fetch and decrypt the recording

The session was recorded as it flowed through the Gateway, sealed, and written
to the WORM store. Wait for it to finalize, then ask the API for a replay URL:

```bash
TOKEN=$(curl -s http://127.0.0.1:8080/v1/oauth2/token -H 'Content-Type: application/json' \
  -d '{"grant_type":"client_credentials","client_id":"quickstart-admin","client_secret":"quickstart-admin-dev-secret"}' | jq -r .access_token)
until curl -s "http://127.0.0.1:8080/v1/recordings" -H "Authorization: Bearer $TOKEN" \
  | jq -e '.items[-1].status == "finalized"' >/dev/null; do sleep 2; done
REC=$(curl -s "http://127.0.0.1:8080/v1/recordings" -H "Authorization: Bearer $TOKEN" | jq -r '.items[-1].id')
URL=$(curl -s -X POST "http://127.0.0.1:8080/v1/recordings/$REC/replay" \
  -H "Authorization: Bearer $TOKEN" | jq -r .url)
```

The URL is short-lived, signed for exactly one object, and points straight at
the object store — recording bytes never pass through the Control Plane. It
names the store's in-network address (`minio:9000`), so route that name to the
published local port while keeping the URL intact (the signature covers it):

```bash
curl -sf --connect-to minio:9000:127.0.0.1:9000 "$URL" -o recording.slrec
head -c 6 recording.slrec; echo
```

`SLREC1` — a sealed object, not a terminal transcript. This is the crown-jewel
property: the recording is encrypted to the **customer recording key**, and
the platform stores only the public half. Nobody with Control Plane access,
object-store access, or a platform admin role can read it. Decrypt it yourself
with the private half (the seed left the demo key on a dedicated volume that
only the decrypt tool mounts; the decryptor is a small offline tool shipped
with this example — its first run builds a container for it):

```bash
docker compose run --rm -T decrypt recording.slrec > session.cast
head -2 session.cast
```

That is a standard [asciicast v2](https://docs.asciinema.org/manual/asciicast/v2/)
file — header line, then timestamped output *and keystroke* events; play it
with any asciinema-compatible player. For a quick look, render just the
terminal output:

```bash
docker compose run --rm -T decrypt --text recording.slrec
```

There is your session — `hello from web-01` — recovered from a
platform-unreadable object with a key only you hold. In production you
generate this key pair yourself, give the platform the public half, and guard
the private half; the Dashboard's player does the same decryption in your
browser, and the key never leaves it.

## 9. Tear down

```bash
docker compose down -v
rm -f recording.slrec session.cast
```

`down -v` removes the database, the recordings, and the demo keys; the built
images stay for a fast next start.

## Next

- [Core concepts](concepts.md) — the architecture you just exercised, in ten minutes.
- [SSH access](../user-guide/ssh-access.md) — addressing modes, `~/.ssh/config`, ProxyJump with `@cert-authority`, all against this stack.
- [Requesting access](../user-guide/requesting-access.md) — walk a JIT request from denied to approved on this stack.
- [Production hardening](../security/hardening.md) — everything this evaluation deliberately relaxed.
