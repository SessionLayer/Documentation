# F-docs-acc-6: troubleshooting.md misquotes the node-unreachable user message
- Severity: low
- Area: accuracy
- Status: Verified-Fixed

## Claim (doc)
`docs/operations/troubleshooting.md:17` (error-taxonomy table) and the heading
at line 82 render the message as `target node is offline / unreachable`, in
code formatting that implies a literal.

## Source evidence
`Gateway/gateway-core/src/ssh/outcome.rs:37`:
`pub const NODE_UNREACHABLE: &str = "the target node is offline or unavailable";`
— "or unavailable", not "/ unreachable". `docs/user-guide/ssh-access.md:203`
and `docs/operations/gateway-runbook.md:31–32` quote it correctly.

## Suggested correction
Use the exact string `the target node is offline or unavailable` in the table
row and adjust the section heading, so an operator grepping logs or matching
the user's report finds it verbatim.

**Fix:** troubleshooting.md taxonomy row + section heading now quote the exact outcome.rs literal 'the target node is offline or unavailable' (re-verified at gateway-core/src/ssh/outcome.rs NODE_UNREACHABLE).
