# F-docs-tone-2: "decision log" is used on six pages but defined on none — and the page it points at never uses the phrase
- Severity: medium
- Area: tone
- Status: Verified-Fixed

Occurrences:
- admin-guides/rbac.md:108 — "recorded in the decision log for admins and auditors ([Audit](audit.md))"
- admin-guides/session-limits.md:76 — "the decision log has the truth"
- user-guide/file-transfer.md:23 — "lands in the decision log for your admin"
- user-guide/requesting-access.md:139 — "ask your admin to check the decision log"
- operations/troubleshooting.md:6, 48 — "the operator-side decision log" / "The decision log records which rule matched…"
- operations/gateway-runbook.md:22 — "correlate with the CP decision log"

Neither reference/glossary.md, getting-started/concepts.md, nor admin-guides/audit.md defines the term, and audit.md — where rbac.md's link sends the reader — never says "decision log" anywhere. A reader can reasonably conclude it is a separate artifact from the audit stream (a file? an endpoint?) and go looking for it.

**Suggested fix:**
- glossary.md, add: "**decision log** — the authorization decisions inside the audit stream: every `authz.decision` event, carrying the matched rule or lock and the full allow snapshot. Not a separate store — search it via `GET /v1/audit-events?action=authz.decision`."
- audit.md, in "Search the stream", add one anchoring sentence, e.g. after the search examples: "The `authz.decision` events are what other pages call the **decision log** — the operator-side truth behind every generic `access denied by policy`."
- Optionally link the first use per page to audit.md (rbac.md already does).

**Fix:** audit.md 'Search the stream' now anchors the term ("The `authz.decision` events … are what other pages call the **decision log**", action name verified in ConnectAuthorizationService.java); first use on rbac.md/session-limits.md/troubleshooting.md/gateway-runbook.md is now linked to audit.md; glossary entry added by T4.
