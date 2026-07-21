# Requesting access

When you need a node your standing grants don't cover, you request just-in-time
(JIT) access: you name the node, the Linux login, and a reason; the right
people approve it; you get a time-boxed grant and connect as usual. This page
walks the flow from the requester's side, end to end, on the quickstart stack.

Prerequisites:

- [ ] The [quickstart](../getting-started/quickstart.md) stack is running and
      you completed it in your current shell (it set `$NODE_ID`; this page
      re-mints `$TOKEN` below).
- [ ] `curl` and `jq` on your machine.

## How a request flows

1. **You submit a request** — target node, Linux login (principal), and a
   mandatory reason. The requester is always the authenticated caller; you
   cannot file a request as someone else.
2. **The approval chain runs.** The matching JIT policy names zero to three
   approval levels, each an email identity or an OIDC group. Zero levels means
   auto-approve. **You can never approve your own request**, no matter what
   permissions you hold — the Control Plane rejects self-approval as a hard
   invariant.
3. **The grant clock starts at final approval.** Your access is time-boxed by
   the policy's maximum TTL. Within that window you connect exactly as you
   would with standing access — same `ssh` command, same recording; the session
   is tagged with the `jit` access model in the audit trail.
4. **The grant expires or is revoked.** Expiry is automatic. An admin can also
   revoke an active grant, which places a lock — new sessions are refused *and*
   your live session is torn down.

A JIT grant elevates you only where you had **no standing rule at all** on the
target node. It never widens an existing standing grant to extra logins (ask
your admin to change the rule instead), and it never overrides a deny or a
lock — deny always wins.

A request moves through these states:

| State | Meaning |
|---|---|
| `PENDING_APPROVAL` | Waiting on the next approval level. |
| `APPROVED` / `ACTIVE` | Granted; the clock is running. A zero-level chain goes here immediately. |
| `DENIED` | An approver denied it (terminal). |
| `EXPIRED` | The approval window or the grant TTL ran out. |
| `REVOKED` | An admin revoked the active grant (and locked it — live sessions die). |

## Try it: from denied to granted

Alice has standing access to `web-01`; Bob has none at all — exactly the
situation JIT is for. Give Bob an identity and a key, watch him get denied,
then walk his request through approval. Run everything from the
`examples/quickstart` directory.

First, refresh the admin token and set up Bob. Real deployments give humans
OIDC identities; the evaluation stack stands in a service account for
`bob@example.com` (this half is an admin's job in production):

```bash
TOKEN=$(curl -s http://127.0.0.1:8080/v1/oauth2/token -H 'Content-Type: application/json' \
  -d '{"grant_type":"client_credentials","client_id":"quickstart-admin","client_secret":"quickstart-admin-dev-secret"}' | jq -r .access_token)
SA_ID=$(curl -s -X POST http://127.0.0.1:8080/v1/service-accounts \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"bob@example.com","description":"quickstart JIT requester"}' | jq -r .id)
BOB_SECRET=$(curl -s -X POST "http://127.0.0.1:8080/v1/service-accounts/$SA_ID/credentials" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"credentialType":"client_secret"}' | jq -r .clientSecret)
docker compose exec -T client sh -c 'ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_bob -q'
BOB_FP=$(docker compose exec -T client ssh-keygen -lf /root/.ssh/id_bob.pub | awk '{print $2}')
curl -s -X POST http://127.0.0.1:8080/v1/pins \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"fingerprint\":\"$BOB_FP\",\"identity\":\"bob@example.com\",\"principals\":[\"dba\"],\"ttlSeconds\":3600}" | jq '{identity, expiresAt}'
```

Create a JIT policy that makes quickstart nodes requestable, with a one-level
approval chain satisfied by the admin identity:

```bash
curl -s -X POST http://127.0.0.1:8080/v1/jit-policies \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"quickstart-jit","targetSelector":{"env":{"op":"eq","value":"quickstart"}},
       "capabilities":["shell","exec"],"maxTtlSeconds":900,
       "approvalChain":[{"kind":"email","value":"quickstart-admin"}]}' | jq '{name, maxTtlSeconds}'
```

Bob can authenticate — but authentication is not access. No rule covers him:

```bash
docker compose exec -T client ssh -p 2222 -i /root/.ssh/id_bob -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=accept-new dba%web-01@gateway 'id' || echo "denied, as expected"
```

Now act as Bob — mint his own API token and submit the request:

```bash
BOB_TOKEN=$(curl -s http://127.0.0.1:8080/v1/oauth2/token -H 'Content-Type: application/json' \
  -d "{\"grant_type\":\"client_credentials\",\"client_id\":\"bob@example.com\",\"client_secret\":\"$BOB_SECRET\"}" | jq -r .access_token)
REQ_ID=$(curl -s -X POST http://127.0.0.1:8080/v1/jit-requests \
  -H "Authorization: Bearer $BOB_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"targetNodeId\":\"$NODE_ID\",\"principal\":\"dba\",\"reason\":\"investigating the quickstart database\"}" | jq -r .id)
curl -s "http://127.0.0.1:8080/v1/jit-requests/$REQ_ID" \
  -H "Authorization: Bearer $TOKEN" | jq '{state, principal, reason}'
```

The request is `PENDING_APPROVAL`. Approve it as the admin (a *different*
identity — the requester's own token would be refused):

```bash
TOKEN=$(curl -s http://127.0.0.1:8080/v1/oauth2/token -H 'Content-Type: application/json' \
  -d '{"grant_type":"client_credentials","client_id":"quickstart-admin","client_secret":"quickstart-admin-dev-secret"}' | jq -r .access_token)
curl -s -X POST "http://127.0.0.1:8080/v1/jit-requests/$REQ_ID/approve" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reason":"approved for the quickstart walkthrough"}' | jq '{state, grantExpiresAt}'
```

The grant clock is running (`grantExpiresAt`, about 15 minutes out). The exact
command that was refused a minute ago now lands Bob on the node as `dba`:

```bash
docker compose exec -T client ssh -p 2222 -i /root/.ssh/id_bob -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=accept-new dba%web-01@gateway 'id'
```

The session appears in the audit trail tagged `jit`, linked to the request and
its approval:

```bash
curl -s "http://127.0.0.1:8080/v1/sessions?accessModel=jit" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.items | sort_by(.startedAt) | last | {identity, principal, accessModel, jitRequestId}'
```

## What denial looks like

Over SSH, every refusal looks the same by design: a generic
`access denied by policy`. The error never tells you whether the node exists,
whether a rule matched, or whether you are locked — that detail lives in the
audit trail, for auditors. If you expected access and were refused, check your
request's state first, then ask your admin to check the decision log.

Your request itself is more talkative: `DENIED` means an approver said no
(their reason is recorded), and `EXPIRED` means nobody decided within the
approval window. Ask your approver rather than re-submitting repeatedly —
every transition is audited.

## When the grant ends

At `grantExpiresAt` the grant lapses; how a *live* session ends is the
operator's mid-session expiry policy (run to completion, grace period, or hard
kill). Revocation is not ambiguous: it locks the grant and tears down live
sessions immediately.

> **Note:** there is also a break-glass path for emergencies (identity provider
> down, approvers unreachable). It is operator-provisioned and alarmed —
> FIDO2 hardware keys or pre-issued offline codes, forced strict recording,
> mandatory review. If you think you need it, that is a conversation with your
> operator, not an API call: see [Break-glass access](../admin-guides/break-glass.md).

## Next

- [SSH access](ssh-access.md) — addressing modes and client configuration.
- [JIT access](../admin-guides/jit-access.md) — the same flow from the admin's side.
- [Break-glass access](../admin-guides/break-glass.md) — the emergency path.
- [Audit](../admin-guides/audit.md) — how requests, approvals, and sessions correlate.
