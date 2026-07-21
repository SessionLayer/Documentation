# F-docs-tone-3: The user-visible "node offline" error is quoted three different ways across four pages
- Severity: medium
- Area: tone
- Status: Verified-Fixed

The suite is rightly strict that user-facing errors are a small fixed set — but then renders one of them inconsistently:

- user-guide/ssh-access.md:203 — "`the target node is offline or unavailable`"
- operations/gateway-runbook.md:31–32 — "target node is offline or **unavailable**"
- admin-guides/nodes.md:237 — "target node is offline or **unreachable**"
- operations/troubleshooting.md:17 and heading at :82 — "`target node is offline / unreachable`"

A reader pasting the message from their terminal into a docs search will miss half the coverage; an operator comparing a user report against troubleshooting.md's taxonomy table sees a string that matches no other page. Exact error strings must be identical everywhere they are quoted.

**Suggested fix:** pick the string the Gateway actually emits (T5b-accuracy should confirm which of "unavailable"/"unreachable" is real — two of the four pages are wrong either way) and normalize all four locations to that exact literal, in backticks. Troubleshooting's heading at :82 should quote the literal too ("## \"Target node is offline or unavailable\"" or the confirmed variant), not a slash-composite.

**Fix (lead closure):** unified on the outcome.rs NODE_UNREACHABLE literal 'the target node is offline or unavailable' — live-verified by T2, source-verified by T3; all quotes now verbatim, descriptors unambiguous.
