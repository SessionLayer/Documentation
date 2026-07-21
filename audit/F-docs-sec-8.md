# F-docs-sec-8: session-recording.md's "can produce ciphertext — and nothing else" enumeration omits the live-capture window at the Gateway
- Severity: low
- Area: security
- Status: Verified-Fixed

**Where:** `docs/admin-guides/session-recording.md:8-14` — "**the platform cannot read its own recordings** … A platform admin, a compromised Control Plane, or SessionLayer's own developers can produce ciphertext — and nothing else. Secrets typed at prompts are captured, but unreadable to everyone except the holder of your key."

**Why it matters:** the sealed-object claim is true, but the enumeration reads as a complete list of compromise scenarios and silently skips the one component that *does* see the content: the Gateway holds every session's plaintext (including those typed secrets) live at capture time, before sealing. A compromised Gateway — or a malicious Gateway release, which is within "SessionLayer's own developers" as an actor — reads and can exfiltrate session content in real time; no customer key needed. The trust model states this loudly as the honest core (`trust-model.md:9-25`: "only the Gateway sees session plaintext"), so the suite is internally inconsistent in strength: a reviewer reading only the recording page concludes "no platform-side compromise reads content", which the trust model explicitly disclaims.

**Risk:** overstated guarantee on the page most likely to be quoted in a customer's own security review ("the single most important fact on this page"). The gap between "recordings at rest are unreadable" and "session content is unreadable" is exactly the gap an assessor needs to see.

**Fix:** one sentence after the enumeration: "The one component that does see session plaintext — live, at capture — is the Gateway itself; that is the Tier-0 trade stated in the [trust model](../security/trust-model.md), and why the hardening checklist treats Gateway placement and integrity as preconditions." Optionally soften "unreadable to everyone except the holder of your key" to "unreadable *from the stored recording* to everyone except…".

**Fix:** session-recording.md adds the Tier-0 pointer ("The one component that does see session plaintext — live, at capture, before sealing — is the Gateway itself…", linking trust-model.md + hardening.md) and softens the claim to "unreadable *from the stored recording*".
