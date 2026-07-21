# F-docs-acc-5: trust-model.md "full residual inventory" omits current Gateway Accepted-Risk records
- Severity: medium
- Area: accuracy
- Status: Verified-Fixed

## Claim (doc)
`docs/security/trust-model.md:174–178`: "The full residual inventory — the
remaining accepted risks on the books … **kept here so nothing is discoverable
only by reading source**." The table then lists only two Gateway entries
(`F-recorder-frame-count-1`, `F-hardening-residuals-s23`).

## Evidence
Gateway convention (`Gateway/audit/README.md`): a finding resolved
(`Verified-Fixed`) **or accepted** (`Accepted-Risk`) moves to `audit/closed/` —
so `closed/` + `Status: Accepted-Risk` IS the Gateway's current accepted-risk
register (the doc itself already sources its two GW rows from there).
`grep -rl 'Status: Accepted-Risk' Gateway/audit/closed/` returns 22 files; the
following are neither superseded by a later session nor in the doc:

Still-current and absent from the inventory (spot-verified against source):
- `F-gw-breakglass-secret-zeroize-1` (med) — break-glass code/token heap copies not zeroized; still true: `gateway-core/src/ssh/handler.rs:175` holds `breakglass_token: Option<String>` (plain String). The file's "carry into the S18 zeroize sweep" plan was not executed for these two values (S21 fixed only the recorder/inner-key items).
- `F-snapshot-empty-retention-1` (med) — a successfully-read empty datastore substitution shrinks the deny-set on resync; the contract-level authority signal it defers is still absent (`lock.proto:70–72` `feed_epoch` is advisory only).
- `F-dep-1` (med label, practical low) — the `rsa` crate remains in `Gateway/Cargo.lock:2956` as an uncompiled optional dep (RUSTSEC-2023-0071 noise).
- `F-otp-transit-1` (low) — OTP is zeroized in the handler but prost/tonic serialization buffers are not.
- `F-sshkey-dup-1` (low) — two `ssh-key` versions coexist (`Cargo.lock:3605`, `3626`).
- `F-lockfeed-fleet-scale-1` (low) — no-jitter reconnect + synchronous global-lock teardown fan-out at very large fleets.
- `F-pty-wantreply-1` (low) — inner `pty-req` sent `want_reply=false` (`gateway-core/src/ssh/innerleg.rs:188`), node PTY-allocation failure silently swallowed.
- `F-gendesync-1` (low) — busy-renew generation-desync latent path (memory: "Gateway shares the F2 busy-renew latent bug").
- `F-cert-local-validation-1` (low, by-design note), `F-gw-breakglass-accepted-notes-1` (low, consolidated), `F-proxy-maxaddr-1` (info), `F-context-gatewayid-bind-1` (info).

Correctly omitted (superseded — no doc change needed, listed to show the
cut-line): `F-ctxsig-1`/`F-perchannel-1` (closed by the S10 verifier +
per-channel re-eval), `F-drain-1` (S15 drain, FR-HA-7 PROVEN),
`F-ha-metrics-accepted-risk`/`F-innermetrics-1`/`F-s10-observability-1`
(S21 OTel). CP `closed/` accepted-risks are likewise superseded or covered
narratively (`F-merkle-anchor-deferred-1` → open `F-merkle-anchor-1`;
`F-device-flow-source-match-1` → the device-flow section). Agent inventory is
accurate against `origin/main` (S24 flipped `F-supplychain-sct-1`/
`-leaf-crossbind-1`/`-golden-1` to Verified-Fixed; the doc correctly lists
only `set-only`, `repro-inputs`, `hardening-1`, `docker-2`).

## Suggested correction
Add the missing current Gateway rows to the inventory table (one line each, in
the table's existing plain-language style), or — if the intent is to list only
deployment-relevant risks — replace the "nothing is discoverable only by
reading source" claim with an honest scope statement and a pointer to
`Gateway/audit/closed/` for engineering-level residuals. The two medium-graded
items (break-glass secret zeroize, empty-snapshot substitution) belong in the
table either way.

**Fix:** trust-model.md inventory gained the 12 missing current Gateway rows (both mediums first: breakglass-secret-zeroize, snapshot-empty-retention; then dep-1, otp-transit, sshkey-dup, lockfeed-fleet-scale, pty-wantreply, gendesync, cert-local-validation, breakglass-accepted-notes, proxy-maxaddr, context-gatewayid-bind) + an intro note that the Gateway register lives in audit/closed/ by that repo's convention. Superseded items stay excluded per the finding's cut-line.
