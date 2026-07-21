# F-docs-sec-6: trust-model.md states compliance-WORM recordings "cannot be deleted by anyone" without the retention-expiry qualifier every other page carries
- Severity: low
- Area: security
- Status: Verified-Fixed

**Where:** `docs/security/trust-model.md:144` — "A compliance-WORM recording cannot be deleted by anyone — including the platform."

**Why it matters:** the claim is only true *until the object's retention period expires*, and retention is an operator-configured setting stamped at write time (default 365 days). Every other page gets this right: `session-recording.md:86` scopes the table to "before retention expires", `faq.md:93-95` says "can delete **before retention expires**", and `glossary.md` says "truly un-deletable **until retention expires**". The trust model is the page written "for the security reviewer who has to sign off" — the one place an unqualified absolute does the most damage. A reviewer could conclude compliance-mode recordings are permanently immutable and design a compliance story on that, when in fact an operator who sets a short default retention gets deletable-after-N-days objects.

**Fix:** one clause: "cannot be deleted by anyone — including the platform — before its retention period expires (retention is yours to set; keep it at or above your regime's floor)." This also makes the sentence consistent with the crypto-shred framing that follows it.

**Fix:** trust-model.md now reads "cannot be deleted by anyone — including the platform — before its retention period expires (retention is yours to set; keep it at or above your regime's floor)", consistent with session-recording.md/faq.md/glossary.md and with the crypto-shred framing that follows.
