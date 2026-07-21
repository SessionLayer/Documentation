# F-docs-sec-3: unpinned `#main` build contexts and clone-and-build install steps carry no supply-chain caveat, in a suite whose headline is verify-what-you-run
- Severity: medium
- Area: security
- Status: Verified-Fixed

**Where:**
- `examples/quickstart/compose.yaml:56` — `src: https://github.com/SessionLayer/ControlPlane-API.git#main`
- `examples/quickstart/compose.yaml:100` — `context: https://github.com/SessionLayer/Gateway.git#main`
- `docs/installation/control-plane.md:16-21` — `git clone …` + build, no tag checkout, no verification step.
- `docs/installation/gateway.md:33-38` — same pattern.

Neither the quickstart, the compose comments, nor the install pages state the implication anywhere.

**Why it matters:** the security section makes release verification a first-class story — `docs/security/supply-chain.md` says every release (explicitly including the Control Plane, Gateway, and Dashboard, `supply-chain.md:48-49`) ships SLSA provenance and a keyless signature, and `hardening.md` step 8 makes verification a go-live precondition for the Agent. Yet the two Tier-0 components' documented acquisition path is "build whatever the tip of `main` is right now", with no pin and no pointer to the verification the platform ships.

**Risk:** a reader — evaluating a *security* product — executes arbitrary unpinned code from a moving branch; a compromised repo or a malicious commit to `main` runs on their machine (quickstart) or lands in their production build (install pages), and nothing in the docs even flags the trade. For the quickstart this is a common dev-eval pattern and arguably acceptable *if stated*; for the production install pages it contradicts the suite's own supply-chain posture. The "silent" part is the finding.

**Fix:** (a) quickstart/compose: pin both contexts to a release tag or commit (`…#vX.Y.Z`), or add an in-line comment stating that `#main` is unpinned, dev-eval-only, and that releases are verified per `docs/security/supply-chain.md`; (b) install pages: check out a release tag in the clone step and add one line pointing at `gh attestation verify` / `cosign verify-blob` for the built-artifact comparison (or state plainly that a from-source build makes your build your provenance, as `installation/agent.md:57-60` already does — that page has the right sentence; CP/GW pages lack it).

**Fix:** In-line unpinned-#main comments on both compose build contexts + an honest Note in quickstart step 1 pointing at docs/security/supply-chain.md (eval-only; production verifies signed releases).
