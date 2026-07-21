# F-docs-acc-3: port-forwarding and X11 capabilities are documented as functional — the Gateway never admits them
- Severity: high
- Area: accuracy
- Status: Verified-Fixed

## Claim (doc)
- `docs/admin-guides/rbac.md:142–151` — the capability table lists `port_forward_local` ("`-L` forwards"), `port_forward_remote` ("`-R` forwards"), and `x11` ("X11 forwarding") as grantable capabilities, with only `agent_forward` marked "**never admitted**". Lines 152–154 add "A withheld capability produces a clear channel-level refusal" — implying a *granted* one is admitted.
- `docs/operations/troubleshooting.md:138–140` — "`sftp`/`scp`/**port-forward** refusals with an explicit channel error mean the capability wasn't granted" — implying granting it stops the refusal.
- `docs/reference/glossary.md` (capability entry) — "one policy-gated thing a session may do: `shell`, `exec`, `sftp`, `scp`, local or remote port forwarding, agent forwarding, or X11".
- `docs/getting-started/concepts.md:85` — "capabilities (shell, exec, SFTP, SCP, port forwarding — each individually …)".

## Source evidence (code wins)
- `Gateway/gateway-core/src/ssh/handler.rs:1898–1918` — `channel_open_direct_tcpip`: a plain local port-forward is refused **unconditionally** ("the capability gate; agent/port forwarding are default-deny"; log `outcome = "port_forward_refused"` at line 1916). No check of the granted capability set exists on this path; the only admitted direct-tcpip is the ProxyJump inner-hop termination.
- `Gateway/gateway-core/src/ssh/handler.rs:1947–1961` — `required_capabilities` maps only `Shell`/`Exec`/`Sftp`+`Scp`; unknown subsystems get an empty set (always refused). No channel kind ever requires `PortForwardLocal`, `PortForwardRemote`, or `X11`.
- No `tcpip_forward` (remote `-R`) handler and no `x11_request` handler exist anywhere in `gateway-core/src/ssh/` (grep: zero hits) — russh's defaults refuse both.
- The vocabulary itself does exist end-to-end (`ControlPlane-API/.../authz/Capabilities.java:17–20`, `contracts/proto/.../authz.proto:73–76`), so the CP will happily *store and sign* these grants — but the Gateway data plane never honors them. Granting `port_forward_local` today changes nothing.
- Consistent with the sign-off: SIGNOFF-MATRIX FR-SESS-2 proof is "channel_open_direct_tcpip (refuse ungranted)" with no positive port-forward test anywhere in the suite.

## Suggested correction
In rbac.md, mark `port_forward_local`, `port_forward_remote`, and `x11` as
"accepted in policy, **not admitted by the Gateway in this release** (channels
are always refused)" — mirroring the existing `agent_forward` warning (whose
refusal is deliberate and permanent; the other three read as vocabulary
reserved ahead of implementation). Drop "port-forward" from the
troubleshooting sentence (a port-forward refusal does NOT mean "grant the
capability and it will work"), and qualify the glossary and concepts.md
enumerations.

**Fix (lead closure):** all five locations fixed: rbac.md table+Note and troubleshooting.md (12f75e9/9052d9f), glossary.md + api.md closed vocabularies (bb0c6f9), concepts.md enumeration (lead). Recorded as product observation OBS-6 in the session RESULT.
