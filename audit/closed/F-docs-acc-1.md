# F-docs-acc-1: file-transfer.md claims transfer content is never captured — legacy scp-over-exec content IS captured in the recording
- Severity: high
- Area: accuracy
- Status: Verified-Fixed

## Claim (doc)
`docs/user-guide/file-transfer.md`:
- Lines 6–7: "Every transfer is audited by protocol decoding … The content itself is **never captured**."
- Lines 90–92: "The transferred bytes are hashed in a streaming pass and discarded — **they appear in no recording** and no audit row."
- Lines 93–95: "The session recording for a transfer channel contains transfer *markers*, not data."
- Lines 97–100: "If your compliance regime requires content capture, SessionLayer does not provide it."

The page also explicitly demonstrates legacy `scp -O` (lines 48–55), the exact
mode where the claim is false.

## Source evidence (code wins)
- `Gateway/gateway-core/src/ssh/recorder/mod.rs:109` — "ALWAYS asciicast (output + input); a legacy scp-over-exec additionally runs an [scp decoder]".
- `Gateway/gateway-core/src/ssh/recorder/mod.rs:226` — "…for a legacy scp-over-exec, whose content is **ALSO captured**".
- `Gateway/gateway-core/src/ssh/recorder/mod.rs:1052–1056` — red-team regression `scp_classified_exec_still_records_asciicast` pins that the exec channel's bytes stay in the asciicast.
- The docs' own `docs/security/trust-model.md:156–158` states it correctly: "legacy `scp`-over-exec transfers land their raw bytes in the terminal capture (modern SFTP-based transfers are content-free, names/sizes/hashes only)". file-transfer.md contradicts trust-model.md and the code.

The *audit row* part is accurate (metadata + SHA-256 only); the recording part
is not: an scp-over-exec channel is an exec channel, and its raw stream (file
bytes included) is sealed into the asciicast recording. Sealed to the customer
key, but decryptable by every holder of replay authority — precisely the
boundary trust-model.md tells the reader to treat carefully.

## Suggested correction
- Line 6–7: "…a SHA-256 of the content. For SFTP and modern `scp` (SFTP mode), the content itself is not captured. Legacy `scp -O` runs over an exec channel, so its raw bytes do land in the (sealed) terminal recording — see the recording-content boundary in the [trust model](../security/trust-model.md)."
- Rework "What is deliberately not captured" (lines 88–100) to scope the "no recording" claim to SFTP-protocol transfers and state the legacy-scp exception explicitly.
- Secondary: `docs/getting-started/concepts.md:118–121` ("names, sizes, and content hashes, never file content") should gain the same one-line qualifier or link.

**Fix (lead closure):** same defect as F-docs-sec-1/tone-5; fixed in 5a225c2 (file-transfer intro scoped, scp -O Warning, concepts clause) — cross-referenced.
