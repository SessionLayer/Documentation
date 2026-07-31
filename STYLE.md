# SessionLayer documentation style guide

This is the voice and structure contract for every page in `docs/`. If a page and this guide
disagree, fix the page.

The rules below are not house taste. Each one is what Teleport, Tailscale, HashiCorp Vault,
Stripe, Caddy, Kubernetes, PostgreSQL, Grafana, Supabase, Django, Cloudflare and Traefik do on
their live pages, or what the Google, Microsoft, Kubernetes and Diátaxis style guides state
explicitly. Where a rule has a source, it is quoted.

## 1. Write these

### 1.1 Open with the mechanism, in one sentence

The first sentence says what the thing is or how it works. No preamble, no roadmap, no restating
the heading.

> Teleport: "You can protect a server with Teleport by running the Teleport SSH Service on the
> server and enrolling it in your Teleport cluster."
>
> Tailscale: "Tailscale is a Zero Trust identity-based connectivity platform that replaces your
> legacy VPN, SASE, and PAM."

Both name the mechanism in the first clause. Neither spends a sentence on what the page will
cover.

### 1.2 Second person, present tense, active voice

"The kubelet preserves node stability", not "will preserve". "You enroll a node with", not "the
node shall be enrolled". Kubernetes' contributor guide makes the present tense a hard rule.

### 1.3 Commands are copy-pasteable, and placeholders are named in prose

Pick one placeholder convention per page and state it once, in words, next to the first command.

> Teleport: "Replace `teleport.example.com:443` with the web address of your Teleport Proxy
> Service."

Never leave a reader to infer what `<value>` means from its shape.

### 1.4 Show real output

A command block that shows only the command teaches half the step. Paste what it actually
printed, so the reader can tell success from failure without being told.

### 1.5 Compress

Microsoft's named technique is "use bigger ideas, fewer words". Their own worked example:

| Before | After |
|---|---|
| "If you're ready to purchase Office 365 for your organization, contact your Microsoft account representative" | "Ready to buy? Contact us." |

Cut every sentence that carries no fact.

### 1.6 Reference pages mirror the code

Tables and definition lists, terse entries, no narrative connective tissue between them. A
reference page's structure should be recognisably the structure of the thing it documents.

### 1.7 Length follows the task

Teleport runs one ~3,500-word getting-started page because getting started is one linear task.
Tailscale splits nearly everything else into short single-purpose articles. Both are correct. A
target word count is not a style rule.

## 2. Do not write these

Each row is a documented tell. The left column is what a machine writes; the right column is the
fix.

| Do not write | Write instead |
|---|---|
| "In this guide, we'll walk through X, Y and Z" | Delete it. Start at step 1. Google: "Don't pre-announce anything in documentation." |
| "It's important to note that", "generally speaking", "essentially" | State the fact, or scope it precisely: "on Linux hosts". |
| Spaced em dashes as connective tissue, several per paragraph | A full stop, or a comma. See §3. |
| "Simply run", "just configure", "easily" | Delete the adverb. Banned by Google and by Kubernetes. |
| "Please ensure you have X installed" | Move it to Prerequisites. Drop "please". |
| Bold for rhetorical emphasis | Bold only what the user clicks. See §4. |
| "In today's fast-paced threat landscape" | Delete the sentence. |
| Restating the heading as the first sentence | State the fact cold. |
| "a robust, scalable, secure solution" | One factual sentence. Adjective triplets are noise. |
| "In summary, by following these steps you have successfully" | State the resulting state, then link onward. |
| Two Diátaxis modes on one page | Split them. Reference explains nothing; how-to teaches nothing. |
| Mixed placeholder styles on one page | Pick one, state it once. |

## 3. Em dashes

**Unspaced, rare, and only for a genuine aside.**

Google's rule is explicit: "Don't put a space before or after it." Microsoft's own worked example
rewrites `pipelines — logical groups —` to `pipelines—logical groups—`.

Most em dashes in a draft are not asides at all. They are two clauses that wanted a full stop:

| Before | After |
|---|---|
| "Deny overrides allow — a lock beats every grant." | "Deny overrides allow. A lock beats every grant." |
| "The Gateway records every session — it is the only component that sees plaintext." | "The Gateway records every session. It is the only component that sees plaintext." |
| "Set `idle_timeout` — the default is 15 minutes — in the policy." | "Set `idle_timeout` in the policy. The default is 15 minutes." |

The one idiomatic survivor is the man-page gloss in reference material, where the dash separates a
name from its one-line definition:

```text
SELECT, TABLE, WITH — retrieve rows from a table or view
```

Even there, prefer a two-column table. A table is machine-checkable and a dash is not.

## 4. Bold

**Bold marks literal UI elements the user clicks: Save, Settings > Access, Approve.** Nothing
else.

Anything the user types is code font, not bold. Anything the user must not miss goes in a
`> **Warning:**` admonition, not in bold mid-paragraph. Tailscale's main explanation page opens
with no bold at all.

Do not bold: the first mention of a term, the subject of a list item, a severity, a default value,
a "not" or "never", or the word you would have said loudly.

## 5. Page skeletons

One Diátaxis mode per page.

**Tutorial.** The H1 is the concrete outcome. One or two sentences saying what gets built.
`Prerequisites` checklist, which may nest mini-install steps with OS tabs. Numbered `Step N`
sections, each command paired with its real output. `Conclusion` stating the working end state.
`Next steps` linking outward.

**How-to.** The H1 is the literal action: "Rotate a certificate authority". One sentence of goal.
Terse prerequisites; this reader is competent. Ordered steps, command then output. **A
verification step.** `See also`.

**Reference.** A one-line synopsis, or one to three flat factual sentences. Then straight into
the table or definition list that mirrors the real structure. Each entry: name, type and default,
one to three sentences, constraints. No "why". Examples, if any, kept together at the end.

**Explanation.** One crisp definition sentence, then short H2s answering discrete real questions:
"Why use X?", "When should I not use X?". This is the only page type where hedged and comparative
language belongs. No steps, no field lists.

Prerequisites headings belong on tutorials and how-tos that genuinely have them. A reference page
does not have prerequisites.

## 6. Accuracy rules (non-negotiable)

- **Derived, never invented.** Every command, config key, port, default, API path and capability
  claim comes from the source repos or specs. If you cannot point at the code or a test, do not
  write it. When docs and code disagree, the code wins and the doc is a bug.
- **Executed, not imagined.** Every runnable procedure is executed end-to-end, exactly as written,
  before it ships. A reader pasting the blocks in order succeeds.
- **No vaporware.** GitOps reconciliation and the external Merkle anchor do not exist. Do not
  present them as available.
- **Security consequences in-line.** Where a step has a security consequence (a dev-only flag, a
  disabled check, an unlimited default), say so right there in a `> **Warning:**`, with the
  production alternative. Never in a footnote.
- **A rewrite never changes a technical claim.** If rewriting surfaces something factually wrong,
  that is a finding: fix it deliberately and record it.

## 7. Mechanics

- One `#` H1 per page, matching its title in `docs/SUMMARY.md`.
- Sentence case for all headings: "Enroll your first node", not "Enroll Your First Node".
- Short paragraphs, four sentences or fewer.
- Every code block has a language tag and is complete and runnable.
- Tables for enumerable facts (ports, flags, event kinds); prose for reasoning.
- Every page ends with a `Next` or `See also` section of two to four links.
- Admonitions are blockquotes with a bold lead, pure Markdown:

  ```markdown
  > **Warning:** this survives every renderer.

  > **Note:** so does this.
  ```

- Diagrams are Mermaid fenced blocks. No images a reader cannot regenerate.
- Pure Markdown only: no inline HTML, no site-generator shortcodes.

## 8. Terminology

Define once in [Core concepts](docs/getting-started/concepts.md) and the
[Glossary](docs/reference/glossary.md); use identically everywhere.

| Term | Use it for | Never |
|---|---|---|
| SessionLayer | the platform as a whole | "SL", "the product" |
| Control Plane | the Java management component (CP after first use per page) | "controlplane", "the API server" |
| Gateway | the Rust data-plane proxy | "gateway server", "proxy" as a name |
| Agent | the per-node outbound connector | "node agent" |
| node | a Linux host you reach through SessionLayer | "server", "target" (except "target node") |
| session | one recorded SSH connection through a Gateway | "connection", once the term is taught |
| access model | standing, JIT, or break-glass | "access mode" |
| lock | the un-overridable deny primitive | "ban", "block" as nouns |
| recording | the sealed asciicast of a session | "capture", "tape" |
| lease | a live session's slot against a session limit | "reservation" |
| data-plane RBAC | who may SSH where | "SSH RBAC" |
| platform RBAC | who may administer SessionLayer | "admin RBAC" |
| session CA / user CA / host CA | the three certificate authorities | "the CA" without qualifying |
| join token | the single-use credential an Agent presents to enroll | "enrollment key" |
| enrollment token | the Gateway's equivalent (matches `bootstrap.enrollment_token`) | "join token" for a Gateway |
| customer recording key | the operator-held key recordings are sealed to | "encryption key" unqualified |

Component names are capitalized (Gateway, Agent, Control Plane); generic nouns are not (a node, a
session, a lock).

## 9. Examples and fake values

Use obviously fake, consistent values everywhere: `alice@example.com` (user), `web-01` (node),
`deploy` (Linux login), `gw.example.com` (Gateway address), `cp.example.com` (Control Plane URL).
Never a real secret, token, key, or internal hostname. Label dev-only credentials dev-only where
they appear.

## 10. Linking

- Link by relative path. Link to a page, not to a heading anchor, when the target is in another
  section; anchors drift.
- The first mention of a defined term on a page links to Core concepts or the Glossary.
- Prefer upstream primary sources for external links (OpenSSH, Vault, PostgreSQL).

## 11. Information architecture

The tree under `docs/` is audience-and-topic shaped: `getting-started`, `installation`,
`admin-guides`, `user-guide`, `reference`, `security`, `operations`. This matches how Teleport
organises its own docs, and it stays.

Diátaxis is enforced **per page** (§5), not by URL. A page in `admin-guides/` is a how-to; a page
in `reference/` is reference; mixing modes on one page is the defect, not the directory it lives
in.

`docs/SUMMARY.md` is the navigation source of truth and is gate-checked against the tree. Any page
added, removed or moved must update it in the same commit.

## 12. Checking your work

Before a page is done, run these against it:

```bash
grep -c ' — ' PAGE.md                                # spaced em dashes: expect 0
grep -oP '\*\*[^*]+\*\*' PAGE.md                     # every hit must be a clickable UI element
grep -oiE '\b(simply|just|easily|easy|please)\b' PAGE.md   # expect none
```

Then read the first sentence out loud. If it announces the page instead of stating a fact, rewrite
it.
