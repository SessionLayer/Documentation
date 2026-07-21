# F-docs-tone-5: file-transfer.md claims content "appears in no recording" without the legacy-scp caveat two other pages carefully make
- Severity: medium
- Area: tone
- Status: Verified-Fixed

The suite's honesty rule is its brand, and two pages get this edge exactly right:

- admin-guides/session-recording.md:29–34 — "> **Note:** one honest edge: legacy `scp` runs over an `exec` channel … a legacy-protocol `scp` transfer's raw bytes **do land inside the sealed recording** …"
- security/trust-model.md:156–158 — "legacy `scp`-over-exec transfers land their raw bytes in the terminal capture"

user-guide/file-transfer.md contradicts them, twice, on the page most likely to be read by the people it affects:

- :6–7 — "The content itself is never captured."
- :90–92 — "**File content.** … The transferred bytes are hashed in a streaming pass and discarded — they appear in **no recording** and no audit row."

And the same page introduces legacy mode at :48–50 ("legacy `scp -O` uses the classic exec mode — SessionLayer decodes and audits both"), so the unqualified "never" is directly reachable from its own text.

**Suggested rewording** — in "What is deliberately not captured", amend the first bullet and add the note:

> - **File content.** The audit is metadata: names, sizes, hashes, direction. For SFTP — including modern `scp`, which rides the SFTP subsystem — the transferred bytes are hashed in a streaming pass and discarded: they appear in no recording and no audit row.
>
> > **Note:** the one honest edge is legacy `scp -O`, which runs over an `exec` channel — and every exec channel is terminal-captured. A legacy-mode transfer's raw bytes therefore do land inside the sealed recording (readable only by the customer recording key holder). Modern OpenSSH (9.0+) uses SFTP for `scp` and is content-free — see [Session recording](../admin-guides/session-recording.md).

Also soften the intro at :6–7 to "content is never captured for SFTP-based transfers" or add "(one legacy-`scp` edge below)".

**Fix:** Same fix set as F-docs-sec-1: intro qualifier, in-line scp -O Warning, capture bullet exception naming the trust model.
