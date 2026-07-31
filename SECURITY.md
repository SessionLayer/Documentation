# Security policy

Report a vulnerability through GitHub's private vulnerability reporting: the
**Security** tab above, then **Report a vulnerability**. That opens a thread
only you and the maintainers can read. Do not open a public issue, pull
request, or discussion for a security finding.

[SessionLayer's vulnerability disclosure policy](docs/security/vulnerability-disclosure.md)
lives in this repository and is the single authority for every repository in
the organization: what to include in a report, full scope, embargo and credit,
and how to verify that the release you installed is the build the advisory
named. Read it before reporting.

## Scope in this repository

This repository is the SessionLayer documentation set. It ships no binary.

In scope: a documented procedure that is insecure as written, and one that
omits a step a reader needs to stay safe. Both are real defects here, because
readers run these pages against production.

Not accepted here: a defect in the software a page describes. That belongs to
that component's repository, which is where the fix ships. The policy lists
the rest of the out-of-scope set, including test fixtures, volumetric
denial-of-service testing, anything starting from a credential the threat
model already assumes lost, and accepted risks already documented in the
[trust model](docs/security/trust-model.md).

## Response targets

The [disclosure policy](docs/security/vulnerability-disclosure.md) carries the
one timeline this organization keeps, from acknowledgement through triage, fix
and embargo, and it covers every repository including this one. Advisories
credit you unless you ask to stay anonymous, and request a CVE for findings
rated moderate or above. There is no bug bounty.
