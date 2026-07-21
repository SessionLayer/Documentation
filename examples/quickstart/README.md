# SessionLayer quickstart assets

The runnable single-host evaluation stack for the
[Quickstart guide](../../docs/getting-started/quickstart.md) — the guide is the
manual for these files and the test that keeps them honest. Start there.

| File | What it is |
| --- | --- |
| `compose.yaml` | The whole stack: Postgres, MinIO (WORM), Control Plane, Gateway, one node, a stock-OpenSSH client, the one-shot seed |
| `cp.Dockerfile` | Multi-stage source build of the Control Plane (the product repo ships a jar, not an image) |
| `seed/` | The one-shot provisioning of everything that has no API surface (CA anchors, Gateway enrollment token, admin service account, demo customer recording key) |
| `node/` | The node image: Debian 13 + stock OpenSSH, trusting only the session CA |
| `client/` | A stock OpenSSH client container, so the guide never touches your host SSH setup |
| `tools/` | `decrypt_slrec.py` — offline decryptor for sealed (`SLREC1`) recordings |
| `pg-init/` | Postgres first-boot init (pgcrypto) |

Everything binds to `127.0.0.1`, every credential is a labeled dev-only
placeholder, and `docker compose down -v` removes all of it.
