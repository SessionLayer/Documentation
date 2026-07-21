# F-docs-tone-8: British/American spelling splits the suite in two — the reference section reads British, the guides read American
- Severity: low
- Area: tone
- Status: Verified-Fixed

STYLE.md's first sentence promises the suite "reads like one author wrote it". The spelling doesn't:

British (concentrated in reference/):
- reference/api.md:40, 182 — "unrecognised"; :366, 370, 476 — "catalogue"
- reference/audit-events.md:5, 16, 49 — "catalogues"/"catalogue"
- reference/config-control-plane.md:146 — "## API behaviour"
- reference/config-gateway.md:65 — "de-synchronise"; :159 — table header "Behaviour"; :170 — "Expiry behaviour"
- reference/glossary.md:21, 51 — "flavour"; :55 — "behaviour"
- reference/ports.md:41 — "signalling"
- "labelled": getting-started/quickstart.md, admin-guides/rbac.md:44, admin-guides/jit-access.md:13, admin-guides/nodes.md, examples/quickstart/README.md (STYLE.md itself uses "labelled")

American (the rest of the suite):
- admin-guides/break-glass.md:122 — "behavior knobs"; operations/monitoring.md:76 — "behavior"; operations/agent-runbook.md:140 — "availability behavior"; security/trust-model.md:49 — "non-behaviors"; admin-guides/high-availability.md:17 — "signaling"; gateway-runbook.md:81 — "signaling"; quickstart.md:113 — "quickstart-labeled"

Note quickstart.md contains both "labelled" (:93 area) and "-labeled" (:113), so the drift exists within single pages, not just between sections.

**Suggested fix:** pick American (the majority in body prose and the likely audience default), normalize the ~16 British spellings above, and add one line to STYLE.md ("American English spelling") so the choice is durable. If British is preferred instead, the change set is the larger guide-side list.

**Fix (lead closure):** American spelling across reference (fc51ee7), admin/ops (12f75e9), examples README (5a225c2).
