# Troubleshooting

SessionLayer's user-facing errors are deliberately a small, fixed set:
pre-authorization errors never reveal whether an identity, node, or rule
exists, so the user's message is often generic by design, and the real
answer lives in the operator-side [decision log](../admin-guides/audit.md),
the `authz.decision` events of the audit stream. This page maps each
symptom to its causes and the page that fixes it.

The error taxonomy in one table:

| What the user sees | When | Specific or generic? |
|---|---|---|
| connection dropped before any SSH banner | source IP outside the global gate, or a PROXY-protocol misconfiguration | silent by design |
| standard SSH authentication failure | all auth methods exhausted | generic |
| `access denied by policy` | authorized-but-denied: rule, lock, quarantine, session limit, or no matching allow | one generic message for all of them |
| `authentication timed out, please reconnect` | device flow not approved in time | specific |
| `the target node is offline or unavailable` | post-authorization: the node cannot be reached | specific, the user is entitled to know the target exists |
| `session cannot start: recording unavailable` | strict recording (always, for break-glass) could not start | specific |
| `service temporarily unavailable` | Control Plane unreachable, new sessions fail closed | specific |

## Connection dropped before any SSH banner

No banner means the TCP connection was cut at accept, before SSH existed.
Two causes:

- Source-IP gate: the client's address is outside the Gateway's global
  CIDR allow-list. Check the Gateway log for the blocked source.
- PROXY protocol v2 misconfiguration, the classic cause when everyone is
  suddenly dropped. The Gateway trusts PROXY headers only from the
  configured load-balancer addresses, and fails closed both ways: a header
  from a non-LB peer is rejected as spoofing, and a missing header from the
  LB is rejected too. So an LB that sends PROXY but is not in the Gateway's
  LB list drops everyone, and an LB that is in the list but is not sending
  PROXY also drops everyone. Align the LB config and the Gateway's
  trusted-LB addresses.

## "Access denied by policy" when the user swears they should have access

The message is identical for every denial reason, on purpose. Do not guess;
read the decision (`$TOKEN` is an admin bearer, see
[Authentication](../admin-guides/authentication.md)):

```bash
curl -s -G https://cp.example.com/v1/audit-events \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "subject=alice@example.com" \
  --data-urlencode "action=authz.decision" \
  --data-urlencode "outcome=denied"
```

Filter on `subject`, not `actor`: the actor on a session decision is the
Gateway that asked, and the human is the subject. The outcome is `denied`,
spelled in full. Both filters match exactly and neither is validated, so a
near miss returns an empty page rather than an error, which reads exactly like
a decision that was never made.

The decision log records which rule matched, which lock applied, or that no
allow matched. The checklist, roughly in observed frequency order:

1. No matching allow, the default. Do the node's labels actually match the
   rule's selector ([RBAC](../admin-guides/rbac.md))? Was the identity's
   group claim present? Device-flow logins carry no groups, see the
   [trust model](../security/trust-model.md) inventory.
2. A lock, including quarantine, a clone-detection auto-lock, or a JIT
   revocation's teardown window ([Locks](../admin-guides/locks.md)).
3. An explicit deny rule: deny-overrides beats every allow.
4. A session limit: at the concurrent cap, attempt N+1 is this same generic
   denial ([Session limits](../admin-guides/session-limits.md)).
5. The requested login is not in the rule's principals, for example
   `ssh deploy%...` against a rule that grants `www`.
6. A JIT grant expired or not yet active. Check the request's clocks
   ([JIT access](../admin-guides/jit-access.md)).
7. The lock feed is unhealthy on that Gateway; it refuses what it cannot
   verify ([Gateway runbook](gateway-runbook.md)).

## Authentication failures

- Every method falls through to device flow unexpectedly: the offered
  certificate or pin is expired or revoked, or the pin's source CIDR does
  not match the client's current network. A changed source falls back to
  interactive rather than hard-failing, see
  [Authentication](../admin-guides/authentication.md).
- `authentication timed out, please reconnect`: the device flow's browser
  approval did not complete in the window. Reconnect and retry; if
  systematic, check the IdP's health and the user's ability to reach the
  verification page.
- Client hangs during device flow: the Gateway sends keep-alive prompts
  about every 10 s during IdP polling; a middlebox with a very aggressive
  idle timeout can still cut it. Check the path's idle limits.

## "The target node is offline or unavailable"

The user was authorized; this is reachability. For an agentless node, can
the Gateway reach `node:22` (routing, firewall, the NetworkPolicy's
node-subnet CIDR)? For an agent node, the Gateway log has the precise cause
(`no_agent_registered`, `dial_back_timeout`,
`agent_refused_or_local_dial_failed`, `missed_heartbeats`,
`agent_signal_saturated`); the [Gateway runbook](gateway-runbook.md) maps
each to an action, and the [Agent runbook](agent-runbook.md) covers the
node side (`LOCAL_DIAL_FAILED` means the node's own `sshd` is down; a
reconnect loop means a TLS/server-name/version mismatch; all channels down
means use out-of-band recovery).

Also check the boring one first: `GET /v1/nodes`. Is the node `active` and
`healthy`, or did someone quarantine it?

## Host-identity verification failures

A session that dies at the inner leg with a host-verification abort (and a
`gateway.host_verify` error span or log) means the node presented a key or
certificate that does not match its enrolled anchor. This is the no-TOFU
guarantee working. Either the node was re-keyed without re-enrollment
(update its anchor, see [Nodes](../admin-guides/nodes.md)), or something is
impersonating the node; investigate before you fix it. The user sees only
the generic node-unreachable message; the detail is operator-side.

## "Session cannot start: recording unavailable"

Strict recording refused the session. In order: is the customer recording
key provisioned ([Session recording](../admin-guides/session-recording.md))?
Is the WORM object store reachable and healthy? Is the Gateway's spool path
writable under its Landlock allow-set
([Gateway runbook](gateway-runbook.md))? For break-glass this is always
strict; restoring the recording path is the incident response.

## "Service temporarily unavailable"

The Control Plane is unreachable from that Gateway; new sessions fail
closed, never open, while established sessions keep flowing to their grant
expiry. Check the CP's health (`GET /v1/healthz`), the Gateway-to-CP mTLS
gRPC path, and, in HA, whether only one instance is affected. If the CA
signer is down, the symptom is the same for new sessions; see
[Monitoring](monitoring.md) for the fast-burn alert.

## Session ends unexpectedly mid-work

Check the session's `endReason` (`GET /v1/sessions/{id}`) and the audit
stream: a pushed lock (incident response, quarantine, JIT revoke), grant
expiry per the access model's mode (run-to-TTL, grace-then-kill, or
hard-kill), an idle timeout (`idle_timeout`, activity-tracked, per
[Session limits](../admin-guides/session-limits.md)), a Gateway drain
deadline during maintenance ([Upgrades](upgrades.md)), or a mid-session
recording failure under strict mode.

The `endReason` vocabulary is closed:

| `endReason` | Means |
|---|---|
| `closed` | An orderly end, and the default when nothing more specific applied. A Gateway drain deadline lands here. |
| `expired` | The authorization's grant expiry was reached. |
| `idle_timeout` | The session's idle timeout elapsed. |
| `locked` | A lock tore it down. |
| `error` | The session ended abnormally, or its recording failed. |
| `truncated` | The recording finalized short of the whole session. |
| `gateway_removed` | Its Gateway's identity was force-removed while the session was still open. |

It is advisory. The authoritative "why" for a teardown is the lock or
decision entry in the audit chain, not this field: a drain and a clean
logout are both `closed`.

## A channel is refused inside a working session

`sftp`/`scp` refusals with an explicit channel error mean the capability
was not granted; by then you are authorized, so the error is allowed to be
specific ([RBAC](../admin-guides/rbac.md)). Port-forward and X11 refusals
are deliberately plainer, a channel-open or request failure with no reason
detail, so check the rule grants the matching capability
(`port_forward_local`, `port_forward_remote`, `x11`) before debugging the
network; a granted `-L` can also fail because the node dials the target and
cannot reach it. In ProxyJump mode every `direct-tcpip` channel is the jump
hop, so `-L` is structurally unavailable there regardless of any grant.
Agent forwarding is refused always, everywhere, by design; granting
`agent_forward` does not stop the refusal. With `ControlMaster`
multiplexing, each new channel re-checks capability, expiry, and locks
locally, so a channel refusal in a long-lived master connection often means
policy changed under it.

## Where the evidence lives

For any session: the audit stream (every decision and transition,
correlated, see [Audit](../admin-guides/audit.md)), the recording (what
actually happened on the terminal), the trace (timing per hop, joined by
session ID), the Gateway log (reason codes), and, in the agent model, the
node's own `sshd` log (the platform-independent second opinion). All five
join on the session ID.

## Next

- [Gateway runbook](gateway-runbook.md): reason-code reference.
- [Agent runbook](agent-runbook.md): node-side symptoms and exit codes.
- [Monitoring](monitoring.md): catching these before users report them.
- [SSH access](../user-guide/ssh-access.md): the client-side setup many
  "failures" trace back to.
