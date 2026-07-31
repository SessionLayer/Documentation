# SessionLayer quickstart assets

The runnable single-host evaluation stack for the
[Quickstart guide](../../docs/getting-started/quickstart.md). The guide is the manual for these
files and the test that keeps them honest. Start there.

| File | What it is |
| --- | --- |
| `compose.yaml` | The whole stack: Postgres, MinIO (WORM), Control Plane, Gateway, one node, a stock-OpenSSH client, the one-shot seed |
| `cp.Dockerfile` | Control Plane image: downloads the signed release jar and its Sigstore bundle, verifies both with `cosign` against the expected release-workflow identity, then runs it on a digest-pinned JRE |
| `gateway.Dockerfile` | Gateway image, built the same verify-then-run way from the signed release binary |
| `seed/` | The one-shot provisioning of everything that has no API surface (CA anchors, Gateway enrollment token, admin service account, demo customer recording key) |
| `node/` | The node image: Debian 13 + stock OpenSSH, trusting only the session CA |
| `client/` | A stock OpenSSH client container, so the guide never touches your host SSH setup |
| `tools/` | `decrypt_slrec.py`, an offline decryptor for sealed (`SLREC1`) recordings |
| `pg-init/` | Postgres first-boot init (pgcrypto) |

The two component images fetch their artifacts from GitHub Releases at build time, so building this
stack needs egress to `github.com`. A verification failure fails the build; there is no fallback to
an unverified artifact. That is the same verify-then-run path described in
[Supply chain](../../docs/security/supply-chain.md), exercised for real.

Everything binds to `127.0.0.1`, every credential is a labeled dev-only placeholder, and
`docker compose down -v` removes all of it.
