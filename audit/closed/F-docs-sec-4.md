# F-docs-sec-4: docs teach client-side TOFU of the Gateway front door (`accept-new` everywhere) while claiming "no trust-on-first-use, anywhere", and never document verifying the Gateway's own host key
- Severity: medium
- Area: security
- Status: Verified-Fixed

**Where:**
- `docs/user-guide/ssh-access.md:41,54,75,109` — `StrictHostKeyChecking accept-new` for the Gateway hop, including in the persistent `~/.ssh/config` blocks that are the production-shaped pattern; `:127-129` explicitly blesses it ("only the jump hop may be `accept-new`").
- `docs/getting-started/quickstart.md:151,170`; `docs/user-guide/file-transfer.md:34,42,53`; `docs/user-guide/requesting-access.md:90,121` — same.
- Contrast the absolute claims: `docs/getting-started/quickstart.md:95-96` "There is no trust-on-first-use anywhere"; `docs/getting-started/how-it-compares.md:53-55` "**Trust-on-first-use, anywhere.** … There is no 'accept and remember' fallback to misconfigure."

**The gap:** nowhere in the suite is the reader told how to verify the *Gateway's own* outer host key — no "operator distributes the Gateway host key / pre-provisions `known_hosts`" step exists on any page, even though the platform persists a stable host key (`ssh.host_key_path`, `docs/reference/config-gateway.md:80`) and the host CA already signs the Gateway's ProxyJump-facing certificate. The `@cert-authority` guidance covers only the inner/jump-target hop.

**Risk:** every client's first connection accepts whatever key the front door presents. A first-connect MITM on the outer hop transparently captures: the OTP typed at keyboard-interactive (single-use, but the attacker races it), the device-flow interaction, and — in username-encoding mode, which has no second verified hop — the *entire session plaintext* thereafter (`accept-new` then pins the attacker's key, making the compromise sticky). The docs' "no TOFU anywhere" phrasing invites the reader to believe this class of attack is designed out; it is only designed out on the platform-side legs. The trust model's ProxyJump accepted-risk (`trust-model.md:134-140`) covers the target hop, not this.

**Fix:** (a) scope the two absolute claims to what they mean: no TOFU *in the platform's own verification* (Gateway→node, Agent, enrollment) — client-side outer-hop verification is the operator's client-config job; (b) add to `ssh-access.md` (and reference from `installation/gateway.md`) the verified path for the front door: publish the Gateway host key fingerprint / pre-provision a `known_hosts` entry (or an `@cert-authority` line for the Gateway name, since the host CA already signs a Gateway host certificate in ProxyJump mode), and prefer `StrictHostKeyChecking yes` with that material in managed client configs; (c) keep `accept-new` only for the explicitly dev-scoped quickstart commands, with one line saying why it is acceptable there (throwaway loopback stack) and what production does instead.

**Fix (lead closure):** claims rescoped (quickstart/how-it-compares/trust-model), new 'Verify the Gateway's host key' section in ssh-access.md executed live, stable host_key_path seeded, accept-new dev-scoped everywhere (5a225c2 + 12f75e9).
