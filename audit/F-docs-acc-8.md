# F-docs-acc-8: ports.md firewall summary forecloses the documented native-recovery path
- Severity: low
- Area: accuracy
- Status: Verified-Fixed

## Claim (doc)
`docs/reference/ports.md:55`: "**Agentless nodes** need inbound `22` from the
Gateways only." and line 61: "Users never reach a node directly — only
through a Gateway."

## Source evidence
The platform deliberately preserves an operator-owned recovery path that is
exactly a direct (non-Gateway) SSH login to the node:
- SIGNOFF-MATRIX FR-ACC-7 (PROVEN): `Gateway/gateway/tests/native_recovery_it.rs` — "a **native non-platform SSH login still succeeds** … the operator-owned independent recovery path"; the inner leg is only an *additive* `TrustedUserCAKeys` line.
- The docs rely on that path elsewhere: `docs/faq.md:42–44` ("Your own native SSH keys and console access remain valid independent recovery paths"), `docs/admin-guides/break-glass.md:157–161` ("the recovery path is … your own native SSH keys or console/serial access").

A firewall built literally from ports.md's summary (node `:22` reachable from
Gateway addresses only) removes the native-SSH half of that recovery story —
leaving only console/serial when the platform is down. That may be a
legitimate posture, but the page states it as the complete matrix ("nothing
here is implied") without noting the trade-off, and "Users never reach a node
directly" is a platform-flow statement presented as a network fact.

## Suggested correction
Add one line to the agentless bullet: "…from the Gateways only — plus, if you
rely on native SSH (rather than console/serial) as your platform-independent
recovery path (see the FAQ and break-glass guide), from your admin/recovery
network." Rephrase line 61 as "Sessions **through the platform** always
transit a Gateway — users have no platform credential that reaches a node
directly."
