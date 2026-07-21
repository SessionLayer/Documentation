# F-docs-sec-5: internal build-workspace artifact referenced in reader-facing repo (`.markdownlint-cli2.jsonc`)
- Severity: low
- Area: security
- Status: Verified-Fixed

**Where:** `.markdownlint-cli2.jsonc:2` — `// Rule choices are documented in Docs/sessions/twentysix/RESULT.md §7.`

**Why it matters:** `Docs/sessions/twentysix/RESULT.md` is an internal build-session artifact from the private development workspace; it does not exist in this repository and never will for a public reader. Shipping the reference (a) leaks the existence and layout of the internal session workspace into a public repo, and (b) leaves a dangling pointer a contributor cannot follow — precisely the class of internal-detail leak the rest of the suite scrubs carefully (all hostnames are documentation-reserved, all credentials labelled fake).

**Fix:** replace the comment with the actual one-line rationale per rule (the information is small: MD013 off because prose wraps, MD024 siblings_only for repeated "Next" H2s, MD036 off for the README's bold lead-ins — the following lines already say most of this), and drop the internal path.

**Fix (lead closure):** internal workspace path replaced with inline rationale (81f2c6c).
