# F-docs-tone-10: Structural-consistency batch — "Where to next" outlier, api.md H1/SUMMARY mismatch, two prerequisite formats
- Severity: low
- Area: tone
- Status: Verified-Fixed

1. **Next heading.** 38 of 39 pages end with `## Next`; getting-started/quickstart.md:259 alone uses `## Where to next`. Rename to `## Next` (or, if the friendlier form is wanted for page 1, say so in STYLE — one outlier is the worst of both).

2. **H1 vs SUMMARY title.** reference/api.md:1 is `# API reference` while docs/SUMMARY.md:30 titles it "API". Every other page matches its SUMMARY title exactly. Fix either side; "API reference" in SUMMARY.md reads better in the nav and matches the in-suite link text ("API reference") used by glossary.md:121, audit-events.md:175, rbac.md:245.

3. **Prerequisite format.** Installation and user-guide pages use an unlabelled checkbox list under "Prerequisites:" (`- [ ] …` — quickstart.md:14, control-plane.md:7, gateway.md:13, agent.md:12, dashboard.md:11, ssh-access.md:10, file-transfer.md:9, requesting-access.md:8), while every admin guide uses a `## Prerequisites` H2 with plain bullets (nodes.md:20, rbac.md:10, authentication.md:9, jit-access.md:11, break-glass.md:21, session-recording.md:41 (nested), session-limits.md:14, locks.md:24, audit.md:10, high-availability.md:12). Two internally-consistent styles; the one-author rule wants one. Recommendation: the `## Prerequisites` H2 (jumpable per STYLE's "descriptive H2s") with checkbox items, applied everywhere.

**Fix (lead closure):** Next H2 unified, api.md H1 aligned to nav, prerequisites format unified to checkbox lists suite-wide (5a225c2, fc51ee7, 12f75e9).
