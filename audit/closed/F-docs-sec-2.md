# F-docs-sec-2: quickstart seed silently disables the recorder's HTTPS requirement (`require_https: false`) with no in-line dev-only warning
- Severity: medium
- Area: security
- Status: Verified-Fixed

**Where:** `examples/quickstart/seed/seed.sh:93-96` — the rendered `/state/gateway.json` contains:

```json
"recorder": {
  "require_https": false
}
```

with no comment, and neither `docs/getting-started/quickstart.md` nor `examples/quickstart/compose.yaml` mentions it. The quickstart's warning block (`quickstart.md:47-52`) enumerates the dev KEK, dev credentials, and loopback binding — but not this.

**Why it matters:** the product default is `true` (`Gateway/gateway-core/src/config.rs:598`), and the reference documents it as a guarded knob: "Set `false` only for a plain-http development MinIO" with an adjacent warning about non-strict mode (`docs/reference/config-gateway.md:126-140`). The suite's own contract (`STYLE.md`, "Security consequences in-line") requires exactly this kind of relaxation to carry a `> **Warning:**` where it appears. Every other dev relaxation in the stack (dev KEK, dev credentials) is labelled; this one is silent.

**Risk:** the quickstart's `gateway.json` is the only complete, working Gateway config a new reader sees. Copying it as a production starting point silently carries `require_https: false`, so sealed recordings upload over cleartext HTTP to the WORM store with no TLS server authentication — an on-path attacker can capture ciphertext at leisure and, worse, impersonate the store endpoint. Because the flag suppresses a fail-closed check, nothing complains later.

**Fix:** (a) add a shell comment in `seed.sh` directly above the heredoc: dev-only, the WORM endpoint here is in-network plain-HTTP MinIO; production keeps the default `true` (link config-gateway.md); (b) add `require_https=false` to the quickstart's existing "dev-only" warning list in `quickstart.md`; (c) optionally have `hardening.md`'s intro ("everything this evaluation deliberately relaxed") name it.

**Fix:** WHY comment added above the seed.sh gateway.json heredoc; require_https: false named in the quickstart's dev-only Warning list with the production default stated.
