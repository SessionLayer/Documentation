# F-docs-acc-2: session-limits.md duration formula wrong — a per-identity policy OVERRIDES the cluster default (it is not min'd with it)
- Severity: high
- Area: accuracy
- Status: Verified-Fixed

## Claim (doc)
`docs/admin-guides/session-limits.md:81–83`: "**Max session duration** is folded
into the decision's grant expiry (`min(policy value, cluster default, the
grant's own TTL)`)…"

## Source evidence (code wins)
- `ControlPlane-API/src/main/java/io/sessionlayer/controlplane/authz/ConnectAuthorizationService.java:562–586` — `resolveSessionCeilings`: per knob, the **most restrictive matching `session_limit_policy` value wins, else the `operator_settings` cluster default, else none**. The cluster default is consulted only when no matching policy sets the knob (lines 578–585).
- `ConnectAuthorizationService.java:430–431` — the resolved ceiling is then `Math.min(ttlSeconds, ceilings.maxSessionSeconds())` against the grant TTL only.
- Same semantics stated in `Docs/sessions/twentyfive/RESULT.md` ("matching `session_limit_policy.max_session_seconds` (else `operator_settings.default_max_session_seconds`)").

Consequence the formula gets wrong: a per-identity policy value **looser** than
the cluster default wins for that population (e.g. policy 4 h, default 1 h →
enforced 4 h, not the doc's 1 h). An admin relying on the documented `min()`
would believe the cluster default is a fleet-wide hard ceiling; it is only the
fallback. The page's own prose at lines 41–43 ("overrides one or more knobs …
an absent knob defers to the cluster default") states it correctly — the page
contradicts itself.

## Suggested correction
Replace the formula with: "`min(resolved ceiling, the grant's own TTL)`, where
the resolved ceiling is the most restrictive value across the *matching
per-identity policies*, falling back to the cluster default only when no
matching policy sets the knob. Note: a per-identity policy can therefore be
*looser* than the cluster default for its population — the default is a
fallback, not a fleet-wide ceiling." Consider the same clarification for
`idle_timeout_seconds` (same resolve path), whose Gateway-side application is
tighten-only against the Gateway's static bound, not against the cluster
default.

**Fix:** session-limits.md now states min(resolved ceiling, grant TTL) with the ceiling = most-restrictive matching policy, cluster default only as the fallback, plus the explicit 'a policy can be looser than the default' consequence; the idle-timeout paragraph gained the same resolve-path note (tighten-only is against the Gateway's static bound). Now agrees with the page's own lines 41-43 and resolveSessionCeilings.
