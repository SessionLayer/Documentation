# Supply chain

Every SessionLayer release ships with the evidence you need to prove that
what you run is what the public CI built from the public source: SLSA
provenance, a keyless Sigstore signature, a CycloneDX SBOM, and a
reproducible-build gate. This guide shows you how to verify a release, and,
for the Agent, how nodes verify themselves before every run and update.

What each release artifact carries:

| Evidence | What it proves | Format |
|---|---|---|
| SLSA provenance (Build L2) | which repository, workflow, and tag built the artifact | Sigstore attestation bundle |
| Keyless cosign signature | the artifact is signed by that CI identity, no signing key exists at rest, anywhere | Sigstore bundle |
| CycloneDX SBOM | the full dependency inventory (itself signed and attested) | CycloneDX JSON |
| Reproducible double-build | the release pipeline builds twice in clean trees and fails on any digest drift | release-gate check |

Signing is keyless: the CI's ephemeral GitHub OIDC identity gets a
short-lived certificate from Fulcio, and the signing event is logged to
Rekor. There is no long-lived signing key to steal, so the thing you verify
is an identity: `SessionLayer/<repo>`'s release workflow, on a version tag,
via GitHub's issuer.

> **Note:** provenance is SLSA Build L2 (attestation minted in the build
> job), not L3, and no hermeticity is claimed. Transparency is proven by
> Rekor's signed timestamp, not a Merkle
> inclusion proof; a bundle missing the timestamp fails closed. Both are
> documented accepted limits, see the [trust model](trust-model.md).

## Cutting a release

Each repo's `.github/workflows/release.yml` triggers on
`push: tags: ['v*']`. The tag push is the entire trigger; there is no
separate "release" button or manual dispatch. Before tagging:

1. Bump the package's own version to match the tag you're about to push
   (`Agent`/`Gateway`: `Cargo.toml`'s `[package] version` /
   `[workspace.package] version`; `ControlPlane`: `pom.xml`'s
   `<version>`; `Dashboard`: `package.json`'s `version`), in
   the same PR as any other pre-flight fix, merged on green `ci.yml` first.
   Nothing currently gates on this at release time, and a forgotten bump is
   not purely cosmetic. cosign identity verification keys off the signed git
   tag alone, so a version mismatch never weakens it. The Agent's
   anti-rollback check is different: the candidate's version comes from the
   signed tag (`VerifiedRelease.version`, parsed out of the certificate SAN),
   but the floor a candidate must beat is the *running* binary's own embedded
   `CARGO_PKG_VERSION`, unless `--current-version` overrides it. A forgotten
   bump therefore ships a binary whose real anti-rollback floor is older than
   its tag implies, silently widening the range of versions a node would
   accept a downgrade to. Keeping the embedded version and the tag in
   lockstep, which is exactly what this step asks for, is what keeps that
   floor honest.
2. For `ControlPlane`, keep the pinned Temurin build (`java-version:
   '25.0.3+9'` in `release.yml`) in lockstep with any deliberate bump: a
   floating minor version drifts the jar's `Build-Jdk-Spec` manifest entry
   across Temurin patch releases and breaks the reproducibility gate.
3. `git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z`, then watch the
   `release` workflow run to completion and confirm the GitHub Release has
   every expected artifact attached (see the per-repo asset list in
   "Verify any release artifact" below).
4. If the run fails, do not try to delete or re-push the tag. You are not
   only trusting yourself to follow that discipline: every repo carries a
   `protect-release-tags` ruleset (`refs/tags/v*`, blocking `update` and
   `deletion`, no bypass actors, including admins) that makes GitHub itself
   refuse it. Annotated tags are the trust anchor cosign/attestation
   verification checks against, and a tag that could be silently moved
   after the fact would defeat the point of a signed release. Fix the root
   cause on `main` (normal PR, green `ci.yml`), then cut the next patch tag
   (`vX.Y.(Z+1)`). A failed tag with no (or an incomplete) GitHub Release
   attached is expected to be left in place: it is the pipeline's own
   record that a defect was caught before anyone could have trusted it, not
   something to hide.

> **Note:** tag protection makes a published `vX.Y.Z` tag immutable, once
> it exists, it cannot be moved to point at different bytes or deleted and
> recreated. It does not bind the signed identity to a commit's content.
> Fulcio's GitHub Actions certificate names the ref that ran the workflow
> (`.../release.yml@refs/tags/vX.Y.Z`), not a commit SHA, so a brand-new
> tag name pushed at an attacker-chosen commit still produces a
> policy-satisfying signature under that same identity pattern. The
> ruleset stops a tag from being moved, not a new tag from being created.
> Tag immutability is what makes a published, already-verified release
> durable; it is not a substitute for verifying which commit a release you
> have not vetted yet actually came from (`git show vX.Y.Z`, or the SLSA
> provenance's build materials).

## Verify any release artifact

With the GitHub CLI, against the repository's attestations. The bare form
below only confirms the attestation traces back to some workflow in
`SessionLayer/Agent`. Pin the exact tag and workflow with
`--cert-identity`/`--source-ref` (or `--signer-workflow`) for the strict
check a real install should use:

```bash
gh attestation verify sessionlayer-agent --repo SessionLayer/Agent

# strict: pin the exact release identity, not any workflow in this repo
gh attestation verify sessionlayer-agent --repo SessionLayer/Agent \
  --cert-identity "https://github.com/SessionLayer/Agent/.github/workflows/release.yml@refs/tags/v0.0.1" \
  --cert-oidc-issuer "https://token.actions.githubusercontent.com" \
  --source-ref "refs/tags/v0.0.1"
```

Or with cosign, pinning the exact workflow identity the release pipeline
signs as:

```bash
cosign verify-blob sessionlayer-agent \
  --bundle sessionlayer-agent.cosign.sigstore.json \
  --certificate-identity "https://github.com/SessionLayer/Agent/.github/workflows/release.yml@refs/tags/v0.0.1" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
# Verified OK
```

Both commands reject what they should: a byte-flipped copy of the binary
fails cosign's signature check, and re-running either command with a
different repo/tag in `--certificate-identity`/`--cert-identity` fails the
identity match (`no matching CertificateIdentity found`) rather than
silently passing.

The same pattern applies to the Gateway, Control Plane, and Dashboard
artifacts and their SBOMs (adjust repo, artifact, and tag).

> **Note:** the Agent's and Gateway's release assets also include a
> `SHA256SUMS` file. It is neither signed nor attested: a plain-text
> checksum list is exactly as forgeable as the binary next to it, so it
> catches accidental transfer corruption, not tampering. Verifying against
> `SHA256SUMS` is not a substitute for the `gh attestation verify` /
> `cosign verify-blob` commands above; use it only as a quick corruption
> check on top of them, never instead of them.

## The Agent: verify-before-run and verify-before-update

The Agent runs on every node, so it gets the strongest treatment: a
built-in offline verifier that checks a candidate binary against a pinned
Sigstore trust root, with no network access, failing closed on any miss.
What it enforces, in order: the signing certificate chains to the pinned
Fulcio roots (and carried a Certificate Transparency proof when the trust
root pins CT keys); a pinned-key Rekor signed timestamp proves the signing
was logged (and is the only clock the verifier trusts); the identity
matches the `SessionLayer/Agent` release workflow policy exactly; and both
the signature and the provenance bind the candidate's exact digest.

### 1. Pin the trust root (once, per fleet)

```bash
cosign trusted-root create --with-default-services > trusted_root.json
sha256sum trusted_root.json    # pin this digest in your config management
```

> **Warning:** this command needs cosign **v3.0.4 or newer**, which is where
> `--with-default-services` was added. Everything earlier rejects it outright
> with `Error: unknown flag: --with-default-services` — being on the 3.x line
> is not enough, since the flag only exists from 3.0.4 on.
> On a version that has the flag, it is still required: without it, `cosign
> trusted-root create` silently emits an empty stub
> (`{"mediaType":"..."}`, 74 bytes), no error, only a trust root with no
> Fulcio/Rekor/CTFE/TSA material, which `sessionlayer-agent verify` would
> then refuse everything against. With the flag, the command produces a
> genuine ~5.7 KB root with populated
> `certificateAuthorities`/`tlogs`/`ctlogs`/`timestampAuthorities`.

The digest pin is the primary control: the tool deliberately never fetches
or refreshes trust material itself. Refresh and re-pin quarterly and
whenever Sigstore announces a key rotation. If verification starts failing
fleet-wide right after a Sigstore rotation, that is the stale-root symptom:
refresh, re-pin, redeploy, never disable verification. (A single node
failing means its local file is corrupt or missing.)

### 2. Verify a downloaded binary

```bash
sessionlayer-agent verify \
  --binary        ./sessionlayer-agent \
  --blob-bundle   ./sessionlayer-agent.cosign.sigstore.json \
  --provenance    ./sessionlayer-agent.provenance.sigstore.json \
  --trusted-root  ./trusted_root.json
# exit 0 = trusted; exit 2 = REFUSED, do not run it
```

A tampered binary, a signature from the wrong repository or workflow, a
forged chain, or a timestamp not bound to this artifact all exit 2.

### 3. Update through the verifier

```bash
sessionlayer-agent update \
  --candidate     ./sessionlayer-agent.new \
  --install-to    /usr/local/bin/sessionlayer-agent \
  --blob-bundle   ./sessionlayer-agent.new.cosign.sigstore.json \
  --provenance    ./sessionlayer-agent.new.provenance.sigstore.json \
  --trusted-root  ./trusted_root.json
```

`update` verifies first and then atomically installs the exact bytes it
verified, never a re-read of the candidate path, so a concurrent swap of
the file cannot smuggle unverified content into place.

> **Warning:** anti-rollback is on by default: a validly signed but older
> release is refused (its version comes from the signed tag, so it cannot
> be forged). `--allow-downgrade` overrides it for a deliberate, audited
> rollback only. A routine pipeline that passes `--allow-downgrade`
> defensively, as a precaution, has reopened the downgrade attack.

### 4. Verify-before-run, at every start

Have the daemon prove its own binary before touching any credential:

```bash
sessionlayer-agent run --node-name web-02 \
  --join-method token --join-token-file /etc/sessionlayer/join-token \
  --cp-endpoint https://cp.example.com:9443 \
  --bootstrap-ca-file /etc/sessionlayer/cp-ca.pem \
  --verify-self \
  --self-blob-bundle   /etc/sessionlayer/agent.cosign.sigstore.json \
  --self-provenance    /etc/sessionlayer/agent.provenance.sigstore.json \
  --self-trusted-root  /etc/sessionlayer/trusted_root.json
```

With `--verify-self`, a binary that was tampered with after install never
gets as far as loading a credential: startup fails closed (exit 2). Bake
these flags into your unit file or DaemonSet; alert on exit code 2 (see the
[Agent runbook](../operations/agent-runbook.md) for the full exit-code
contract).

For a private Sigstore deployment, the pinned identity policy (issuer,
workflow SAN, source repository) is overridable via the `--expect-*` flags.
Run `sessionlayer-agent verify --help` for the set.

## Reproducing a build independently

Each release's double-build gate proves the pipeline reproduces itself; to
reproduce independently, match the documented preconditions: the pinned
Rust toolchain (1.95.0) and committed lockfile with `--locked`, the release
tag's commit timestamp as `SOURCE_DATE_EPOCH`, the same `protoc` version,
**the same base image the release workflow ran on** (`ubuntu-latest`,
currently Ubuntu 24.04 "noble"), and (for the Control Plane jar) the pinned
Temurin JDK build. Path remapping for the workspace, the cargo registry,
and the double-build gate's own alternate target directory is applied by the
release workflow via `RUSTFLAGS`; SBOM timestamps/serial numbers are
normalized. Skip any of these preconditions, and an independent rebuild
differs in exactly that input.

> **Warning:** the base image is a real precondition, not a formality, and
> it is the one most easily missed — the remap rules address *paths*, and
> nothing in `RUSTFLAGS` normalizes the host C toolchain. Rebuilding the
> Agent's release on Ubuntu 26.04 (glibc 2.43, gcc 15.2) with every other
> precondition matched — same tagged commit, same pinned rustc 1.95.0, same
> `SOURCE_DATE_EPOCH`, same `protoc` 3.21.12 — produces a **different**
> digest, differing in `.text` (+10752 bytes) and `.comment`, the section
> that carries the producer version string. The embedded rustc sysroot hash
> is identical in both and neither binary contains a host path, so the
> remapping is working; the C toolchain and libc are simply build inputs
> too. The same rebuild inside a `ubuntu:24.04` container reproduces the
> released digest byte-for-byte. So the digest is independently
> re-derivable, but only in a matching environment: the double-build gate
> proves same-image determinism, which is a real property and a narrower
> one than cross-environment reproducibility.

A recipe that reproduces the Agent's release digest exactly: `ubuntu:24.04`
with `build-essential` and `protobuf-compiler`, rustup `1.95.0` (minimal
profile), `SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)` at the release tag,
then `cargo build --release --locked --bin sessionlayer-agent`.

> **Note:** `build.rs` (tonic-prost-build) generates code under `OUT_DIR`,
> which lives under the target directory, not under the checkout root, and a
> panic location in that generated code embeds `OUT_DIR`'s absolute path.
> The gate's second build points `CARGO_TARGET_DIR` outside the checkout
> root specifically to prove reproducibility from a genuinely different
> build directory, so the remap rule has to cover the alternate target
> directory too (`Agent`/`Gateway` `release.yml`), not just the checkout
> root — miss it, and that path escapes remapping and the two builds'
> digests diverge.

## SBOMs

Every release attaches a CycloneDX SBOM per artifact (spec 1.5 for the two
Rust components, the tooling maximum, and 1.6 for the JVM and npm ones),
signed and provenance-attested like the artifact itself. Feed them to your
vulnerability-management tooling; the platform's own dependency posture is
pinned toolchains, committed lockfiles, an exact-match license allow-list,
and a hard ban on the OpenSSL C stack in the Rust components.

## Next

- [Production hardening](hardening.md): trust-root pinning as a go-live
  precondition.
- [Agent runbook](../operations/agent-runbook.md): exit codes and the
  fleet-wide-failure symptom.
- [Trust model](trust-model.md): the SET-only transparency and L2 limits,
  in context.
- [Upgrades](../operations/upgrades.md): rolling verified updates through a
  fleet.
