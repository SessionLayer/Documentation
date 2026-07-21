# SessionLayer documentation style guide

This is the voice and structure contract for every page in `docs/`. It exists so
the whole suite reads like one author wrote it. If a page and this guide
disagree, fix the page.

## Voice

- **Second person, present tense, active voice.** "You enroll a node with…" —
  never "the node shall be enrolled".
- **Task-first, example-first.** Open each guide with what the reader will have
  when they're done. Show the command or config first; explain after.
  Prerequisites go at the top as a short checklist.
- **Friendly, not chatty.** Plain words over spec-speak: say "connection" before
  you say "outer leg", then teach the precise term once (in
  [Core concepts](docs/getting-started/concepts.md)) and use it consistently.
  Warmth comes from anticipating stumbling points — "If you see `X`, it means
  Y — do Z" — not from jokes.
- **Honest.** State what the platform does not do, plainly and where it matters.
  Limits and accepted risks are features of the documentation, not
  embarrassments to bury.

## Accuracy rules (non-negotiable)

- **Derived, never invented.** Every command, config key, port, default, API
  path, and capability claim comes from the source repos or specs. If you cannot
  point at the code or a test, do not write it. When docs and code disagree, the
  code wins and the doc is a bug.
- **Executed, not imagined.** Every runnable procedure is executed end-to-end,
  exactly as written, before it ships. Copy-paste fidelity: a reader pasting the
  blocks in order succeeds.
- **No vaporware.** Do not document unbuilt features (GitOps reconciliation and
  the external Merkle anchor do not exist — do not present them as available).
- **Security consequences in-line.** Where a step has a security consequence
  (a dev-only flag, a disabled check, an unlimited default), say so right there
  in a `> **Warning:**`, with the production alternative. Never in a footnote.

## Structure

- One `#` H1 per page; it matches the page's title in `docs/SUMMARY.md`.
- Descriptive H2s a reader can jump by. Sentence case for all headings
  ("Enroll your first node", not "Enroll Your First Node").
- Short paragraphs — four sentences or fewer.
- Every code block is complete and runnable, with a language tag. No
  `<placeholders>` unless the immediately preceding line says exactly how to get
  the value.
- Tables for enumerable facts (ports, flags, event kinds); prose for reasoning.
- Every page ends with a **Next** section of 2–4 links.
- Admonitions are blockquotes with a bold lead, pure Markdown:

  ```markdown
  > **Warning:** this survives every renderer.

  > **Note:** so does this.

  > **Tip:** and this.
  ```

- Diagrams are Mermaid fenced blocks (GitHub renders them). No images that a
  reader cannot regenerate.
- Pure Markdown only: no inline HTML, no site-generator shortcodes.

## Terminology

Define once in [Core concepts](docs/getting-started/concepts.md) and the
[Glossary](docs/reference/glossary.md); use identically everywhere.

| Term | Use it for | Never |
|---|---|---|
| SessionLayer | the platform as a whole | "SL", "the product" |
| Control Plane | the Java management component (CP after first use per page) | "controlplane", "the API server" |
| Gateway | the Rust data-plane proxy | "gateway server", "proxy" as a name |
| Agent | the per-node outbound connector | "node agent" |
| node | a Linux host you reach through SessionLayer | "server", "target" (except "target node" in prose) |
| session | one recorded SSH connection through a Gateway | "connection" once the term is taught |
| access model | standing, JIT, or break-glass | "access mode" |
| lock | the un-overridable deny primitive | "ban", "block" as nouns |
| recording | the sealed asciicast of a session | "capture", "tape" |
| lease | a live session's slot against a session limit | "reservation" |
| data-plane RBAC | who may SSH where | "SSH RBAC" |
| platform RBAC | who may administer SessionLayer | "admin RBAC" |
| session CA / user CA / host CA | the three certificate authorities | "the CA" without qualifying |
| join token | the single-use credential an Agent presents to enroll | "enrollment key" |
| enrollment token | the Gateway's equivalent of the join token (matches the `bootstrap.enrollment_token` config key) | "join token" for a Gateway |
| customer recording key | the operator-held key recordings are sealed to | "encryption key" unqualified |

Component names are capitalized (Gateway, Agent, Control Plane); generic nouns
are not (a node, a session, a lock).

## Examples and fake values

Use obviously fake, consistent values everywhere: `alice@example.com` (user),
`web-01` (node), `deploy` (Linux login), `gw.example.com` (Gateway address),
`cp.example.com` (Control Plane URL). Never a real secret, token, key, or
internal hostname. Dev-only credentials in examples are labelled dev-only where
they appear.

## Linking

- Link liberally to other pages by relative path; link to a page, not a heading
  anchor, when the target is in another section (anchors drift).
- The first mention of a defined term on a page links to Core concepts or the
  Glossary.
- External links: prefer upstream primary sources (OpenSSH, Vault, Postgres
  docs).
