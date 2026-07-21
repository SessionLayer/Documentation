# F-docs-tone-12: "Tier-0" is load-bearing on nine pages but has no glossary entry
- Severity: low
- Area: tone
- Status: Verified-Fixed

"Tier-0" carries real weight in the suite — it names the trust class the whole security story hangs on — and appears on nine pages: getting-started/concepts.md:136, getting-started/how-it-compares.md:86, installation/gateway.md:7, admin-guides/rbac.md:159, security/trust-model.md:20, security/hardening.md:168, reference/metrics.md:12, operations/monitoring.md:6, operations/agent-runbook.md:121 (log literal).

concepts.md:135–137 defines it only in passing ("The Gateway and the CAs are a fully-trusted **Tier-0** component…"), and reference/glossary.md — which claims to be "the platform vocabulary, defined once" — has no entry. A reader landing on gateway.md or metrics.md meets the term cold with no link.

**Suggested fix:** add to glossary.md (alphabetical position between "standing access" and "user CA"):

> - **Tier-0** — the platform's fully-trusted component class: the Gateway (the one process that sees session plaintext) and the certificate authorities. Zero trust relocates trust here rather than eliminating it; Tier-0 is why the [hardening checklist](../security/hardening.md) exists.

Optionally link the first "Tier-0" on installation/gateway.md:7 and metrics.md:12 to the glossary per STYLE's first-mention rule.

**Fix (lead closure):** Tier-0 glossary entry + first-mention links (81f2c6c, fc51ee7).
