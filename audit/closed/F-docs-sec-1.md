# F-docs-sec-1: file-transfer.md claims content is "never captured" while teaching legacy `scp -O`, whose bytes land in the recording
- Severity: high
- Area: security
- Status: Verified-Fixed

**Where:**
- `docs/user-guide/file-transfer.md:6-7` — "Every transfer is audited by protocol decoding … The content itself is never captured."
- `docs/user-guide/file-transfer.md:48-51` — the page then teaches legacy mode: "legacy `scp -O` uses the classic exec mode — SessionLayer decodes and audits both".
- `docs/user-guide/file-transfer.md:90-92` — "**File content.** … The transferred bytes are hashed in a streaming pass and discarded — they appear in no recording and no audit row."
- `docs/getting-started/concepts.md:119-121` — repeats the unqualified claim ("names, sizes, and content hashes, never file content").

**Why it is wrong:** the platform's own pages state the opposite for legacy scp — `docs/security/trust-model.md:156-158` ("legacy `scp`-over-exec transfers land their raw bytes in the terminal capture") and `docs/admin-guides/session-recording.md:29-34` (the "honest edge" note). The Gateway source confirms it: every exec channel is always asciicast-captured, and a legacy scp-over-exec's content is *also* captured (`Gateway/gateway-core/src/ssh/recorder/mod.rs:109` and `:226` — "whose content is ALSO captured"; there is even a red-team test that a `scp`-lookalike exec still records).

**Risk:** a user reads the file-transfer page (the page they would actually consult before moving a sensitive file), runs `scp -O secrets.tar …` believing "the bytes appear in no recording", and the full file content lands inside the sealed session recording — readable by every holder of `recording:replay` plus the customer recording key, and retained for the full WORM retention period. The user ends up with sensitive content in a recording without knowing, on the strength of a doc statement the vendor's own trust model contradicts.

**Fix:** in `file-transfer.md`, (a) qualify the intro claim to "SFTP-protocol transfers (including modern `scp`)"; (b) add the same `> **Note:**` honest-edge admonition session-recording.md carries, in-line right at the `scp -O` example in the SCP section; (c) fix the "What is deliberately not captured" bullet to exclude legacy `scp -O` explicitly and link the trust model. In `concepts.md`, add "(one exception: legacy `scp -O`, see File transfer)" or equivalent one-clause qualifier.

**Fix:** file-transfer.md intro + capture bullet scoped to SFTP-protocol transfers, in-line Warning added at the scp -O step, trust-model cross-linked; concepts.md recording paragraph carries the legacy-scp exception clause.
