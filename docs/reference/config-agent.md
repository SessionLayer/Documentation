# Agent configuration

The Agent is configured entirely on the command line — flags and a few environment variables, no
config file. This page lists every flag per subcommand with its default, derived from the Agent's
CLI definitions and drift-checked in CI.

The binary is `sessionlayer-agent` with three subcommands: `run` (join the platform and maintain the
identity), `verify` (check a release binary's signature and provenance), and `update` (verify a
candidate and atomically install it). Invoked with no subcommand it prints a ready banner and exits.

> **Note:** `sessionlayer-agent run` refuses to start as root — before any credential work. A root
> Agent could read the node's host key and impersonate the node. Run it as a dedicated
> unprivileged user.

## Global flags

| Flag | Type | Default | Effect |
|---|---|---|---|
| `--version-json` | switch | off | Print the machine-readable version descriptor as JSON and exit. |
| `--log` | string | unset | Tracing filter (for example `debug`, `sessionlayer_agent=trace`). Overrides `RUST_LOG`. |

## `run`

Joins the platform, maintains the renewable mTLS identity, and (with Gateway endpoints configured)
holds the outbound control channels that make the node reachable.

### Identity and join

| Flag | Type | Default | Effect |
|---|---|---|---|
| `--node-name` | string | required | The stable node identity this Agent joins as. |
| `--join-method` | `token` \| `oidc` \| `mtls` | `token` | How the Agent bootstraps. See [Install the Agent](../installation/agent.md). |
| `--join-token` | string (secret) | — | Token/OIDC join: the credential inline. Prefer the file form. |
| `--join-token-file` | path | — | Token/OIDC join: a file holding the credential. |
| `--operator-cert-file` | path | — | mTLS join: the operator certificate (PEM). Required with `--join-method mtls`. |
| `--operator-key-file` | path | — | mTLS join: the operator ECDSA P-256 key (PKCS#8 PEM). |
| `--cp-endpoint` | URL | `https://127.0.0.1:9443` | The Control Plane mTLS gRPC endpoint. |
| `--cp-server-name` | string | `controlplane` | The server name the Control Plane certificate must carry (SNI + SAN). |
| `--bootstrap-ca-file` | path | required | Operator-pinned Control Plane bootstrap trust anchor (PEM) — never trust-on-first-use. |
| `--data-dir` | path | `/var/lib/sessionlayer-agent` | Credential directory with a single-writer lock. |
| `--connect-timeout-secs` | int (s) | `10` | Connect timeout to the Control Plane. |
| `--rpc-timeout-secs` | int (s) | `30` | Per-RPC timeout. |

### Gateway connectivity

Omit `--gateway-endpoint` to run identity-only (enroll and renew, no data path).

| Flag | Type | Default | Effect |
|---|---|---|---|
| `--gateway-endpoint` | `wss://` URL, repeatable | none | Gateway to dial out to. An HA Agent holds two or more control channels to failure-domain-diverse Gateways. |
| `--gateway-failure-domain` | string, positional-zip | endpoint host | Failure-domain label (rack/AZ) for the corresponding endpoint: one per endpoint, exactly one for all, or none. Two channels must span at least two domains. |
| `--gateway-server-name` | string, positional-zip | `gateway` | The enrolled Gateway name whose serverAuth SAN is verified for the corresponding endpoint. |
| `--min-control-channels` | int | `1` | Warn when live control channels drop below this. Single-instance keeps `1`; HA operators set 2+. |
| `--splice-addr` | `host:port` | `127.0.0.1:22` | The node-local address a dial-back is spliced to. Must be loopback — the Agent refuses to start otherwise. |
| `--max-concurrent-splices` | int | `32` | Cap on simultaneous spliced sessions across all control channels. |
| `--drain-deadline-secs` | int (s) | `30` | How long live sessions may drain after the Agent stops taking new work. |

### Mode and hardening

| Flag | Type | Default | Effect |
|---|---|---|---|
| `--once` | switch | off | Enroll or renew once and exit — no renew loop, no control channel. Used by CI and provisioning checks. |
| `--require-full-landlock` | switch | off | Abort startup unless Landlock (filesystem + network egress) is fully enforced. Default accepts a documented degrade on kernels lacking it (network ABI needs Linux ≥ 6.7). |
| `--verify-self` | switch | off | Verify this binary's Sigstore signature, SLSA provenance, and release identity at startup, and refuse to run on failure. Requires the three `--self-*` paths. |
| `--self-blob-bundle` | path | — | The cosign blob-signature bundle for this binary. |
| `--self-provenance` | path | — | The SLSA provenance bundle for this binary. |
| `--self-trusted-root` | path | — | The pinned Sigstore `trusted_root.json`. |

## `verify`

Verifies a binary offline against the pinned Sigstore trust root: signature, SLSA provenance, and
release identity. Exit `0` if it would be trusted to run or install; exit `2` on any failure. See
[Supply chain](../security/supply-chain.md).

| Flag | Type | Default | Effect |
|---|---|---|---|
| `--binary` | path | required | The candidate binary to verify. |
| `--blob-bundle` | path | required | The cosign blob-signature Sigstore bundle. |
| `--provenance` | path | required | The SLSA provenance attestation bundle. |
| `--trusted-root` | path | required | The pinned Sigstore trusted root (operator-supplied). |
| `--expect-source-repo` | string | `https://github.com/SessionLayer/Agent` | Override the trusted source repository. |
| `--expect-workflow-ref-prefix` | string | the pinned `…/Agent/.github/workflows/release.yml@refs/tags/v` prefix | Override the trusted workflow-ref SAN prefix. |
| `--expect-oidc-issuer` | string | `https://token.actions.githubusercontent.com` | Override the trusted OIDC issuer. |

> **Note:** overriding any `--expect-*` value targets a custom Sigstore identity and relaxes the
> certificate-transparency requirement (a private Sigstore may run no CT log). The pinned production
> identity always requires CT.

## `update`

Verifies a downloaded candidate exactly like `verify` and, only if it passes, atomically installs
it. An unverified binary is never written into place; by default a candidate older than or equal to
the running version is refused (anti-rollback).

| Flag | Type | Default | Effect |
|---|---|---|---|
| `--candidate` | path | required | The downloaded candidate binary. |
| `--blob-bundle` | path | required | The cosign blob-signature bundle for the candidate. |
| `--provenance` | path | required | The SLSA provenance bundle for the candidate. |
| `--trusted-root` | path | required | The pinned Sigstore trusted root. |
| `--install-to` | path | required | Where the verified binary is atomically installed. |
| `--current-version` | string | the running Agent's version | Anti-rollback floor; a candidate must be newer than or equal to it. |
| `--allow-downgrade` | switch | off | Permit installing an older or equal signed release (disables anti-rollback). |

## Exit codes

The process exit status is the Agent's primary health signal — wire your orchestrator to alert on
the non-zero codes rather than blindly restarting.

| Exit code | Meaning | What to do |
|---|---|---|
| `0` | Clean shutdown (or `--once` completed). | Nothing. |
| `2` | `verify`/`update` refused: the binary could not be proven a signed SessionLayer release. | Do not run or install the binary; check the bundles and trust root. |
| `3` | Clone detected: identity renewal hit a generation mismatch — another process renewed with this credential. The platform auto-locks the identity. | Treat as a security event. See the [Agent runbook](../operations/agent-runbook.md). |
| `4` | Repair needed: the credential was rejected terminally (for example revoked or corrupt state). | Re-provision: clear the data dir and re-join with a fresh join token. |

An orchestrator restart policy that treats `3` and `4` like a crash produces a visible crash loop by
design — the Agent will not silently re-join over a security stop.

## Environment

| Variable | Effect |
|---|---|
| `RUST_LOG` | Tracing filter (default `info`); `--log` wins over it. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Enables the OTLP trace exporter (unset ⇒ off). See [Metrics](metrics.md). |
| `OTEL_SERVICE_NAME` | Overrides the reported service name (default `sessionlayer-agent`). |

## Next

- [Install the Agent](../installation/agent.md)
- [Agent runbook](../operations/agent-runbook.md)
- [Supply chain](../security/supply-chain.md)
- [Gateway configuration](config-gateway.md)
