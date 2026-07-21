# Supply chain

Every SessionLayer release ships with the evidence you need to prove that
what you run is what the public CI built from the public source: SLSA
provenance, a keyless Sigstore signature, a CycloneDX SBOM, and a
reproducible-build gate. This guide shows you how to verify a release — and,
for the Agent, how nodes verify **themselves** before every run and update.

What each release artifact carries:

| Evidence | What it proves | Format |
|---|---|---|
| SLSA provenance (Build L2) | *which* repository, workflow, and tag built the artifact | Sigstore attestation bundle |
| Keyless cosign signature | the artifact is signed by that CI identity — no signing key exists at rest, anywhere | Sigstore bundle |
| CycloneDX SBOM | the full dependency inventory (itself signed + attested) | CycloneDX JSON |
| Reproducible double-build | the release pipeline builds twice in clean trees and fails on any digest drift | release-gate check |

Signing is keyless: the CI's ephemeral GitHub OIDC identity gets a
short-lived certificate from Fulcio, and the signing event is logged to
Rekor. There is no long-lived signing key to steal, so the thing you verify
is an *identity* — `SessionLayer/<repo>`'s release workflow, on a version
tag, via GitHub's issuer.

> **Note:** stated honestly: provenance is SLSA **Build L2** (attestation
> minted in the build job) — not L3, and no hermeticity is claimed. And
> transparency is proven by Rekor's signed timestamp, not a Merkle inclusion
> proof; a bundle missing the timestamp fails closed. Both are documented
> accepted limits — see the [trust model](trust-model.md).

## Verify any release artifact

With the GitHub CLI, against the repository's attestations:

```bash
gh attestation verify sessionlayer-agent --repo SessionLayer/Agent
```

Or with cosign, pinning the exact workflow identity the release pipeline
signs as:

```bash
cosign verify-blob sessionlayer-agent \
  --bundle sessionlayer-agent.cosign.sigstore.json \
  --certificate-identity "https://github.com/SessionLayer/Agent/.github/workflows/release.yml@refs/tags/v0.1.0" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
```

The same pattern applies to the Gateway, Control Plane, and Dashboard
artifacts and their SBOMs (adjust repo, artifact, and tag).

## The Agent: verify-before-run and verify-before-update

The Agent runs on every node, so it gets the strongest treatment: a built-in
**offline** verifier that checks a candidate binary against a pinned Sigstore
trust root, with no network access, failing closed on any miss. What it
enforces, in order: the signing certificate chains to the pinned Fulcio
roots (and carried a Certificate Transparency proof when the trust root pins
CT keys); a pinned-key Rekor signed timestamp proves the signing was logged
(and is the only clock the verifier trusts); the identity matches the
`SessionLayer/Agent` release workflow policy exactly; and both the signature
and the provenance bind the candidate's exact digest.

### 1. Pin the trust root (once, per fleet)

```bash
cosign trusted-root create > trusted_root.json
sha256sum trusted_root.json    # pin this digest in your config management
```

The digest pin is the primary control — the tool deliberately never fetches
or refreshes trust material itself. Refresh and re-pin quarterly and whenever
Sigstore announces a key rotation. If verification starts failing
**fleet-wide** right after a Sigstore rotation, that is the stale-root
symptom: refresh, re-pin, redeploy — never disable verification. (A *single*
node failing means its local file is corrupt or missing.)

### 2. Verify a downloaded binary

```bash
sessionlayer-agent verify \
  --binary        ./sessionlayer-agent \
  --blob-bundle   ./sessionlayer-agent.cosign.sigstore.json \
  --provenance    ./sessionlayer-agent.provenance.sigstore.json \
  --trusted-root  ./trusted_root.json
# exit 0 = trusted; exit 2 = REFUSED — do not run it
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

`update` verifies first and then atomically installs **the exact bytes it
verified** — never a re-read of the candidate path, so a concurrent swap of
the file cannot smuggle unverified content into place.

> **Warning:** anti-rollback is on by default: a validly signed but **older**
> release is refused (its version comes from the signed tag, so it can't be
> forged). `--allow-downgrade` overrides it for a deliberate, audited
> rollback only — a routine pipeline that passes `--allow-downgrade`
> "just in case" has re-opened the downgrade attack.

### 4. Verify-before-run, at every start

Have the daemon prove its **own** binary before touching any credential:

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

With `--verify-self`, a binary that was tampered with *after* install never
gets as far as loading a credential — startup fails closed (exit 2). Bake
these flags into your unit file or DaemonSet; alert on exit code 2 (see the
[Agent runbook](../operations/agent-runbook.md) for the full exit-code
contract).

For a private Sigstore deployment, the pinned identity policy (issuer,
workflow SAN, source repository) is overridable via the `--expect-*` flags —
run `sessionlayer-agent verify --help` for the set.

## Reproducing a build independently

Each release's double-build gate proves the pipeline reproduces itself; to
reproduce independently, match the documented preconditions: the pinned Rust
toolchain (1.95.0) and committed lockfile with `--locked`, the release tag's
commit timestamp as `SOURCE_DATE_EPOCH`, the same `protoc` version, and (for
the Control Plane jar) the pinned Temurin JDK build. Path remapping for the
workspace and the cargo registry is applied by the release workflow via
`RUSTFLAGS`; SBOM timestamps/serial numbers are normalized. These
preconditions are the honest residual — an independent rebuild that skips
them will differ in exactly those inputs.

## SBOMs

Every release attaches a CycloneDX SBOM per artifact (spec 1.5 for the two
Rust components — the tooling maximum — and 1.6 for the JVM and npm ones),
signed and provenance-attested like the artifact itself. Feed them to your
vulnerability-management tooling; the platform's own dependency posture is
pinned toolchains, committed lockfiles, an exact-match license allow-list,
and a hard ban on the OpenSSL C stack in the Rust components.

## Next

- [Production hardening](hardening.md) — trust-root pinning as a go-live
  precondition.
- [Agent runbook](../operations/agent-runbook.md) — exit codes and the
  fleet-wide-failure symptom.
- [Trust model](trust-model.md) — the SET-only transparency and L2
  limits, in context.
- [Upgrades](../operations/upgrades.md) — rolling verified updates through
  a fleet.
