# F-docs-tone-13: Quickstart (book page 1) drops precise terms before any page has taught them, without inline links
- Severity: low
- Area: tone
- Status: Verified-Fixed

SUMMARY.md order puts quickstart.md before concepts.md, and the quickstart mostly handles this well (it teaches "pin" inline at step 5, glosses "WORM" implicitly at step 8). Three spots still assume vocabulary only concepts.md/glossary.md teach, with no inline link — the Next section's concepts link is after the fact:

1. quickstart.md:159–161 — "Behind the one command: source gate, pin authentication, a signed authorization decision, a fresh **inner certificate**, host-key verification against your pin, and a recorder on the bridged session." — "inner" (legs) and "source gate" are untaught here. Cheapest fix: link the sentence — "…a fresh [inner certificate](concepts.md) …" — or gloss: "a fresh inner certificate (the Gateway's own short-lived cert toward the node)".
2. quickstart.md:193–194 — "The same API searches by identity, node label, source IP, capability, and **access model**" — first bare use of a defined term; link to [Core concepts](concepts.md) or the glossary.
3. quickstart.md:10–11 — "a WORM object store (MinIO)" — first use in the book; add the two-word gloss "(write-once)" here rather than waiting for step 8's context.

Info-level, same theme: quickstart.md:42 "Gateway enrollment token" is also a first-contact term — covered by F-docs-tone-1.

**Fix:** quickstart: WORM glossed as write-once at first use, inner certificate linked+glossed in step 6, access model linked to concepts in step 7.
