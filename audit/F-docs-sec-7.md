# F-docs-sec-7: quickstart mounts the customer recording private key (via the shared `state` volume) into the recorded node and client containers
- Severity: low
- Area: security
- Status: Verified-Fixed

**Where:** `examples/quickstart/compose.yaml` — the single `state` volume holds `/state/customer_key.pem` (written by `seed/seed.sh:117-121`) and is mounted read-only into `web-01` (line 120), `client` (line 130), and `gateway` (line 107), when each of those needs only one or two specific public files (`session_ca.pub`, `host_ca.pub`, `ca.pem`/`gateway.json` respectively).

**Mitigations already present (why this is low, not higher):** the key is `chmod 600` root-owned, and the Gateway image runs uid 65532, so *the one container where it would break the demo's story cannot read it* — that part is well done. The whole stack is also a single-host throwaway where host root owns everything anyway.

**Risk:** root inside `web-01` — the node being recorded — can read the key that decrypts its own session recordings, and root inside `client` can too. A reader who lifts this compose file as a multi-host template inherits "the fleet's recording-decryption key rides along in a volume mounted into every container", which contradicts the model the quickstart itself teaches ("the private half stays in a local volume" / production keeps it offline). It also quietly co-locates the (consumed, single-use) Gateway enrollment token config with all other services.

**Fix:** either give the customer key its own volume mounted only into `seed` and `decrypt`, or mount per-file (`state/session_ca.pub:/state/session_ca.pub:ro` for the node, etc.). Cheapest acceptable alternative: a one-line comment on the `state` volume in `compose.yaml` saying the co-mount is a single-host dev convenience and that production keeps the private key offline (per `docs/admin-guides/session-recording.md`).

**Fix:** Customer private key moved to a dedicated customer-key volume mounted only into seed and decrypt (node/client/gateway see /state public material only); decrypt re-executed green against the new layout; compose volume comment states the production posture.
