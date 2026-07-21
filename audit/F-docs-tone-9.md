# F-docs-tone-9: Component-capitalization drift (batch) — lowercase "agent"/"gateway" as the component, and "CP" before "Control Plane"
- Severity: low
- Area: tone
- Status: Verified-Fixed

STYLE.md: component names are capitalized (Gateway, Agent, Control Plane); generic nouns are not. Lowercase uses where the word means the component (not "agent node"/"agentless"/"agent transport" descriptors, which are fine):

- installation/agent.md:94–95 — "a compromised *root* agent could read the node's host keys" → "root Agent"
- admin-guides/nodes.md:126 — "a compromised *root* agent could read the host key" → "root Agent"
- admin-guides/high-availability.md:85 — "agent control channels close so agents fail over" → "so Agents fail over"; :145 — "configuring agents with failure-domain-diverse channels" → "Agents"
- installation/gateway.md:75 — "(gateway enrollment deliberately has no REST endpoint" → "Gateway enrollment"
- reference/api.md:197–198 — "configuration management can re-provision an agent without a human" → "an Agent"
- admin-guides/certificate-authorities.md:25 — "No credential a user or agent holds" → "user or Agent" (it means the component's credential)
- faq.md:64 — "## Do I need an agent on every node?" → "Do I need an Agent on every node?" (the answer's body capitalizes it)
- reference/config-gateway.md:183 — "two missed intervals deregister the agent" → "the Agent"
- operations/gateway-runbook.md:40 — "don't chase the agent" → "the Agent"; :49 — "agents would be told to dial back" → "Agents" (:39's "a slow-but-alive agent" likewise)

Not defects (leave alone): "SSH agent forwarding"/"forwarding your agent" (rbac.md:159 — the OpenSSH agent, correctly lowercase), verbatim log lines ("presence: standby (another gateway owns this node)"), command/paths (`sessionlayer-agent`), and "agent node"/"agent model" descriptors.

CP abbreviation (STYLE: "CP after first use per page"):
- security/hardening.md:32 — "On every CP, Gateway, and node host" appears before the page's first "Control Plane" (:52). Spell out at :32 or move the gloss up.
- operations/agent-runbook.md — uses bare "CP" throughout (:14, :16, :28, etc.) and never spells "Control Plane" once. Add it to the intro: "…dials out to your Gateways and the Control Plane (CP)."

**Fix (lead closure):** capitalization sweep applied across all owners' pages (12f75e9, fc51ee7, 5a225c2).
