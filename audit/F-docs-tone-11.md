# F-docs-tone-11: Small terminology/example-value nits (batch)
- Severity: low
- Area: tone
- Status: Verified-Fixed

1. **Certificate key-id rendered two ways.** `session_id + identity`: concepts.md:76, nodes.md:44, gateway-runbook.md:121. `session id + identity` (no underscore): certificate-authorities.md:45, audit.md:88. It's a literal embedded in the cert key ID — normalize to the underscored form everywhere.

2. **OTP expanded three ways.** ssh-access.md:134/157–158 says "one-time passcode" (and the quoted Gateway prompt literal is "One-time passcode:", so *passcode* is the product's word); reference/glossary.md:81 defines OTP as "a single-use, short-TTL **password**"; authentication.md:24, 99 says "single-use **code**". Align glossary (and ideally authentication.md's first expansion) on "one-time passcode".

3. **Wildcard-DNS example suffix drift.** installation/gateway.md:145–146 and reference/config-gateway.md:87 use `*.ssh.example.com` / `web-01.ssh.example.com`; the teaching page user-guide/ssh-access.md (:27, :69, :76, :79, :82, :122) uses `*.nodes.example.com` throughout. Same concept, two invented zones — a reader wiring `ssh.node_dns_suffixes` from the reference while following the user guide gets mismatched examples. Standardize on `*.nodes.example.com` (the user guide has 6 uses to the others' 3) and consider adding it to STYLE's fake-values list.

4. **Single first-person slip.** security/trust-model.md:25 — "…that trade-off is real, and we would rather state it than paper over it." The only "we" in the suite. Suggested: "…that trade-off is real, and this page states it rather than papering over it."

5. **"lease" first mention unlinked.** admin-guides/session-limits.md:72 uses "live session leases" without linking the defined term (glossary/concepts) — STYLE wants the first mention of a defined term linked. Link it (and this is the page that leans on the term most).

6. **README component count vs table.** README.md:35 says "SessionLayer is three components, each in its own repository:" and is followed by a four-row table that includes the Dashboard. concepts.md's "three components" excludes the Dashboard deliberately. Suggested: "SessionLayer is three components plus an admin UI, each in its own repository:".

7. **nodes.md invents "offline" as a health state.** nodes.md:234–236 lists the `health` enum (`healthy`, `unhealthy`, `unreachable`, `unknown`) then says an agent node "is \"offline\"" — a value not in the enum (it is the user-facing error word). Suggested: "an agent node reports `unreachable` whenever its Agent holds no control channel — users see the generic node-offline error."

**Fix (lead closure):** batch nits applied by all owners; nodes.md health wording kept conservative (no unverified enum transition claimed).
