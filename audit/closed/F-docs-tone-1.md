# F-docs-tone-1: Gateway "enrollment token" vs canonical "join token" — the suite splits one STYLE term in two
- Severity: medium
- Area: tone
- Status: Verified-Fixed

**STYLE.md terminology table:** `join token — the single-use agent/gateway enrollment credential — never "enrollment key"`. The table makes one term cover both components.

**What the suite actually does:**
- Agent-side pages consistently say **join token** (installation/agent.md, admin-guides/nodes.md:89–104, reference/api.md:186–199, reference/audit-events.md:65–66, operations/agent-runbook.md:36–37, reference/glossary.md:68).
- Gateway-side pages consistently say **enrollment token**: getting-started/quickstart.md:42 ("a single-use Gateway enrollment token"), examples/quickstart/README.md:11, installation/gateway.md:72, 94, reference/config-gateway.md:34, 52, 57, reference/config-control-plane.md:20 ("TTL of the single-use Gateway enrollment token").
- The two definition pages contradict each other: getting-started/concepts.md:156 says join token = "the single-use credential that enrolls an Agent **or Gateway**", while reference/glossary.md:68 scopes join token to "the credential **an Agent** presents to enroll" and defines no term at all for the Gateway's credential.

A reader who learns "join token" from concepts.md and then installs a Gateway never sees the term again; a reader who greps the glossary for "enrollment token" finds nothing. The code keys (`bootstrap.enrollment_token`, `runtime.gateway_enrollment_token`, `sessionlayer.mtls.enrollment-token-ttl`) are frozen, so the prose must bridge.

**Suggested fix (pick one, apply everywhere):**
1. Preferred: keep "enrollment token" as the Gateway-side surface term (it matches every config key) and make the bridge explicit:
   - glossary.md, add: "**enrollment token (Gateway)** — the Gateway's join token: the single-use, short-TTL credential a Gateway presents to enroll (config key `bootstrap.enrollment_token`). The Agent's equivalent is the [join token]."
   - glossary.md:68, amend join token to: "…credential an Agent presents to enroll. The Gateway's equivalent is its enrollment token."
   - installation/gateway.md:72, first use: "single-use enrollment token (the Gateway's join token)".
2. Alternative: amend STYLE.md's table to name both ("join token (Agent) / enrollment token (Gateway)") so the contract matches the suite.

Either way, concepts.md:156 and glossary.md:68 must stop disagreeing.

**Fix (lead closure):** enrollment token / join token split bridged in STYLE.md, concepts.md, glossary.md, installation/gateway.md (81f2c6c).
