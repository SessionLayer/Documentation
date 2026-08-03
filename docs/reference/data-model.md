# Data model

The Control Plane's Postgres schema is frozen and versioned through Flyway migrations
`V2`-`V29` (`src/main/resources/db/migration` in ControlPlane is the authoritative shape; this
page explains it). Every table lives in one of two Postgres schemas, `config` or `runtime`.

## Conventions

### Config vs runtime

| | Postgres schema | Class | `origin` column? |
|---|---|---|---|
| CONFIG | `config` | Operator-authored desired state (UI + API over Postgres, the single source of truth) | Yes, on every table |
| RUNTIME | `runtime` | Live operational state (locks, sessions, grants, issuance records, presence) | No |

The split is enforced by Postgres role grants: the runtime connects as the non-owner, least-privilege
`cp_runtime` role (introduced by `V11`, see [Schema history](#schema-history-by-migration) below), so
"runtime writes only under the restricted role" is structural, not conventional. Flyway's own
`flyway_schema_history` stays in `public`; no application table lives there.

Every config row carries `origin text NOT NULL DEFAULT 'default' CHECK (origin IN ('api','ui','default'))`
(tightened from an original four-value set including `git` by `V21`, once an external
config-automation client was descoped; config is UI + API only). `lock` (`runtime.access_lock`) is
RUNTIME and carries no `origin`: it is API-only by design, never a config edit.

### Primary keys

Every table's primary key is a `uuid`, generated application-side as UUIDv7
(`io.sessionlayer.controlplane.data.Uuids#v7`). The one exception is `runtime.presence`, keyed by its
`node_id` (1:1 with `node`). UUIDv7's time-ordered prefix gives index locality on high-write tables
(`audit_event`, `ssh_session`, `presence`, `jit_request`); there is no `gen_random_uuid()`/`pgcrypto`
use, so no Postgres extension is required by this schema.

Because the id is client-assigned (non-null before insert), every entity also carries an
`@Version Long version` column: Spring Data R2DBC determines "new" by `version == null`, so a
client-set-UUID insert is not mistaken for an update. The same column doubles as optimistic
concurrency for the generation-counter renewal race on `agent_identity`/`gateway_identity`; a
`BEFORE UPDATE` trigger additionally rejects any `generation` decrease at the DB layer (defense in
depth, [§ Append-only audit](#append-only-audit-monotonic-counters-write-once-recording)).

### Timestamps

All time columns are `timestamptz`; the Java type is `java.time.Instant` (r2dbc-postgresql 1.1.1's
native `InstantCodec` needs no converter). `created_at`/`updated_at` are bookkeeping, managed by
Spring Data R2DBC auditing (`@EnableR2dbcAuditing` + `@CreatedDate`/`@LastModifiedDate`,
`Instant.now()` UTC). Domain timestamps that carry meaning are set explicitly by the writer, never by
auditing: `audit_event.occurred_at`, `ssh_session.started_at`/`ended_at`, `*.expires_at`,
`presence.last_seen`, `jit_request.requested_at`. Columns keep a `DEFAULT now()` for a raw/`psql`
insert that could otherwise miss a bookkeeping value, but the application always supplies it.

### Enums

Closed value sets are `text` columns with an inline `CHECK (col IN (...))`, never a native Postgres
`ENUM` (a native enum can't drop a value and can't add one transactionally).

The table below is authoritative for what the database will store. That is a different question
from what the API will accept. A CHECK is widened and never narrowed, because a narrowing migration
would fail at startup on exactly the deployment that already holds the old value, so the
application-level gate is free to be stricter. In two places it is, and both are noted under the
table. Where the two differ, the API's set is the one a call must satisfy;
[API reference](api.md) states it.

| Domain | Column(s) | Allowed values | Default |
|---|---|---|---|
| origin | config `*.origin` | `api`, `ui`, `default` | `default` |
| connector kind | `node_policy.connector_kind`, `node.connector_kind` | `agent`, `agentless` | none |
| rule effect | `dp_rule.effect` | `allow`, `deny` | none |
| lock mode | `access_lock.mode` | `strict`, `best_effort` | none |
| access model | `ssh_session.access_model`, `audit_event.access_model` | `standing`, `jit`, `breakglass` | none |
| JIT state | `jit_request.state` | `REQUESTED`, `PENDING_APPROVAL`, `APPROVED`, `DENIED`, `EXPIRED`, `ACTIVE`, `REVOKED` | `REQUESTED` |
| identity/credential status | `agent_identity.status`, `gateway_identity.status` | `active`, `locked`, `revoked` | `active` |
| join method | `agent_identity.join_method`, `gateway_identity.join_method`, `join_token.join_method` | `token`, `oidc`, `mtls` | none |
| CA kind | `ca_config.ca_kind` | `user`, `session`, `host`, `mtls` | none |
| CA backend | `ca_config.backend` | `local`, `aws_kms`, `azure_keyvault`, `vault` | none |
| CA algorithm | `ca_config.algorithm` | `ecdsa-p256`, `ecdsa-p384`, `ecdsa-p521`, `ed25519`, `rsa-2048`, `rsa-4096` | `ecdsa-p256` |
| CA rotation state | `ca_config.rotation_state` | `incoming`, `active`, `outgoing`, `expired` | `active` |
| capability | element of every capability set | `shell`, `exec`, `sftp`, `scp`, `port_forward_local`, `port_forward_remote`, `agent_forward`, `x11` | `shell`,`exec` |
| audit outcome | `audit_event.outcome` | `success`, `failure`, `denied`, `error` | none |
| node status | `node.status` | `pending`, `active`, `quarantined`, `removed` | `pending` |
| node health | `node.health` | `unknown`, `healthy`, `unhealthy`, `unreachable` | `unknown` |
| WORM mode | `recording_ref.worm_mode` | `compliance`, `governance` | none (nullable) |
| break-glass auth path | `breakglass_policy.auth_path` | `fido2`, `offline_code` | `fido2` |
| break-glass review | `breakglass_activation.review_status` | `pending`, `reviewed` | `pending` |
| SA auth method | `service_account.auth_method` | `private_key_jwt`, `mtls`, `client_secret` | `private_key_jwt` |
| role-binding subject | `role_binding.subject_kind` | `user`, `group` | none |

`ca_config.ca_kind` gained `mtls` in `V14` for the internal mTLS CA (expand/contract on the named
CHECK; existing SSH-CA rows untouched).

Three of these sets are wider than what the API accepts or the platform can use, and each difference
is deliberate:

- `ca_config.backend`. All four values store, and `local`, `aws_kms` and `azure_keyvault` sign.
  `vault` is a seam whose classes consume an interface nothing in this build implements, so the
  write path refuses it with a `422` and the signer path fails closed on it, asking one shared
  predicate rather than two lists that could drift. The CHECK keeps all four because a deployment
  may already hold a `vault` row from before that gate, and narrowing it would fail at startup on
  exactly that deployment.

- `ca_config.algorithm`. Only the three ECDSA curves can be assembled into a signer, so
  `POST`/`PUT /v1/cas` rejects `ed25519`, `rsa-2048` and `rsa-4096` with a `422`, and rejects a
  curve the chosen backend cannot produce with a `422` as well. The three stay in the CHECK, and in
  the contract's `CaAlgorithm` enum, so a row an upgraded deployment already holds still reads back
  rather than failing the read. That legacy row is what `GET /v1/cas/{caKind}/public-key` returns a
  `409` for: the export will not emit an OpenSSH line for an algorithm that has no OpenSSH key
  type. `ecdsa-p521` was added to the CHECK by `V29`, closing the opposite gap, where a fully
  implemented curve was unreachable.
- `operator_settings.recording_key_seal_algorithm`. The Gateway seals with ECIES on P-256 and
  nothing else, so `PUT /v1/operator-settings/recording-customer-key` accepts only `ecies_p256` and
  refuses `rsa_oaep_sha256` with a `422`. A key stored under the other value would refuse every
  session at the first recording, so the refusal happens at the write, where the error can still
  name the cause.

Platform-permission vocabulary (every element of `platform_role.permissions` must be a member,
widened by `V18`/`V20`/`V23`/`V28`/`V29`): `rbac:read`, `rbac:write`, `node:enroll`,
`node:quarantine`, `node:remove`, `gateway:enroll`, `gateway:remove`, `ca:manage`, `ca:rotate`,
`request:approve`, `recording:replay`, `recording:export`, `recording:delete`,
`recording:key-manage`, `audit:read`, `user:manage`, `settings:write`, `lock:read`, `lock:write`,
`breakglass:manage`.

Unlike the enum table above, this set is not merely mirrored by the application: the CHECK and
`PlatformPermissions.ALL` must be identical, because the seeded `platform-admin` role carries every
member and a divergence makes the first-admin bootstrap violate the constraint at boot. The Control
Plane's `MigrationIntegrityIT` asserts that lockstep, and a docs CI check asserts that this page,
[RBAC](../admin-guides/rbac.md) and the [API reference](api.md#closed-vocabularies) all still match
the source.

### Structured selectors and sets

`jsonb` columns: `dp_rule.identity_selector`, `dp_rule.node_label_selector`,
`dp_rule.source_ip_condition`, `jit_policy.target_selector`, `jit_policy.approval_chain`,
`jit_request.approval_chain`/`approvals`, `access_lock.target_selector`, `join_token.scope`,
`role_binding.scope`, and the label maps `node_policy.desired_labels`/`node.resolved_labels`. Each
non-null selector carries `CHECK (jsonb_typeof(col) = 'object')` (or `'array'` for the chains). The
Java type is `com.fasterxml.jackson.databind.JsonNode` via a converter to r2dbc-postgresql's `Json`
wrapper. An approval chain is capped at length 3: `CHECK (jsonb_typeof(approval_chain) = 'array' AND
jsonb_array_length(approval_chain) <= 3)`; length 0 is allowed (a lock still fails closed at chain 0).

Capability sets are `text[]` with a subset CHECK: `CHECK (capabilities <@ ARRAY['shell','exec','sftp',
'scp','port_forward_local','port_forward_remote','agent_forward','x11']::text[])`. A GIN index backs
the audit "search by capability" query. `principals` and `platform_role.permissions` are also
`text[]` (`permissions` carries its own subset CHECK against the permission vocabulary).

### Snapshot vs foreign key: history must outlive config

Within one class, FKs are real: `recording_ref.session_id → ssh_session` (1:1), `presence.node_id →
node`, `agent_identity.node_id → node`, `role_binding.role_id → platform_role`. Across
runtime→config, there is never a hard FK: the runtime row stores a snapshot of what was decided
instead. `ssh_session`/`jit_request` copy the decision inputs/outputs onto the row: `matched_rule_id
uuid` (a plain uuid, no FK) plus the resolved `principal`, `capabilities`, `access_model`,
`policy_epoch`, `grant_expiry`. Every snapshot ref also stores the human-readable name alongside the
id, so a GC'd config row still leaves legible history: `ssh_session.matched_rule_name`,
`jit_request.jit_policy_name`, `breakglass_activation.breakglass_policy_name`, and the existing
`node_name`/`gateway_name` snapshots.

`audit_event` has zero FKs. All its references (`correlation_id`, `session_id`, `subject`, `node_id`,
`node_labels`) are plain values or snapshots, so no GC anywhere can orphan, block, or alter an audit
row; `node_labels` is a jsonb label snapshot so search-by-label still works after a node is
relabeled or removed.

Runtime→runtime FKs that could otherwise block history retention use `ON DELETE SET NULL`:
`ssh_session.node_id`, `ssh_session.gateway_id`, `ssh_session.jit_request_id`,
`ssh_session.breakglass_activation_id`. The one exception is `recording_ref.session_id`, which is
`ON DELETE RESTRICT`: a session prune must never cascade-erase a recording's object key,
encryption-key reference, or hash-chain head, so a retention pruner has to be recording-aware.

### Append-only audit, monotonic counters, write-once recording

`audit_event` is append-only, enforced in the database: a `BEFORE UPDATE OR DELETE` row trigger and a
`BEFORE TRUNCATE` statement trigger (`runtime.audit_event_immutable()`) raise an exception. The
trigger stops the honest/ORM/normal-DML path; it does not stop a holder of the app's DB role if that
role owns the table or is a superuser. Closing that requires the runtime to connect as a non-owner,
non-superuser role granted only `INSERT, SELECT`: the `cp_runtime` role, `V11`, below.

Hash chain columns are reserved: `audit_event.prev_hash`/`record_hash` (row chain) and
`recording_ref.hash_chain_head` (recording chain). Because UUIDv7 is time-ordered but not a gapless
total order, `audit_event` also carries `seq bigint GENERATED ALWAYS AS IDENTITY` (UNIQUE), a
DB-assigned monotonic ordinal for a single well-defined predecessor and gap/fork detection; `seq` is
DB-only and not mapped by the ORM.

The generation counter (`agent_identity.generation`, `gateway_identity.generation`) has two guards:
the `@Version` optimistic lock (app) and a `BEFORE UPDATE` trigger
(`runtime.enforce_generation_monotonic()`) that rejects any decrease. The guard is per-row: a fresh
active identity for a re-provisioned node legally restarts a new lineage at 0. `presence.nonce` (the
anti-stale-ownership fencing token) gets the identical guard
(`runtime.enforce_presence_nonce_monotonic()`), so a stale or duplicated Gateway cannot re-claim a
node with a lower nonce.

Presence is written only through the CP `Presence` gRPC service: the owning Gateway claims/refreshes
ownership via `Presence.Heartbeat` and relinquishes via `Presence.Release`. The owner is always the
authenticated mTLS peer `gateway_id`, never a request field. Single-instance and HA modes write the
same rows; only the signaling transport differs.

Recording provenance is write-once: a `BEFORE UPDATE` trigger on `recording_ref`
(`runtime.enforce_recording_ref_write_once()`) rejects any change to `session_id` / `object_key` /
`encryption_key_ref` (and to `hash_chain_head` once set). Operational fields (`worm_mode`,
`size_bytes`) stay mutable. All triggers/functions are `CREATE OR REPLACE`, so a manual re-apply
during a repair is idempotent.

### Reserved SQL names

| Design name | Physical table | Note |
|---|---|---|
| `session` | `runtime.ssh_session` | `session` is a reserved word. |
| `lock` | `runtime.access_lock` | `lock` is reserved/fragile; also the clearest place to encode "API-only". |

All other names are kept verbatim (`node`, `presence`, `pin`, `otp`, `dp_rule`, …).

### R2DBC mapping notes

| Postgres type | Java type | Converter |
|---|---|---|
| `jsonb` | `JsonNode` | Two custom converters to/from r2dbc-postgresql's `Json` wrapper; a bare `String` bound to a `jsonb` column fails. |
| `text[]` | `List<String>` | Native (`ArrayCodec`/`StringArrayCodec`); `List` not `String[]` keeps `equals` value-based. |
| `timestamptz` | `Instant` | Native `InstantCodec`. Always UTC. |
| `uuid` | `java.util.UUID` | Native `UuidCodec`. |
| IP/CIDR (`text` + `CHECK (runtime.is_ip_or_cidr(col))`) | `String` | r2dbc-postgresql 1.1.1 has no `cidr` codec and its `inet` codec drops the prefix, so IP/network columns are `text` with a format-validating CHECK, cast to `inet`/`cidr` at query time. `is_ip_or_cidr` parses leniently with `::inet` (host bits allowed) and turns bad input into a clean CHECK-constraint violation rather than a raw cast error. Used by `pin.source_cidr`, `otp.source_cidr`, `audit_event.source_ip`. |

Entities map with `@Table(schema = "config"|"runtime", name = "...")`; R2DBC emits schema-qualified
SQL, so no `search_path` dependency.

## Migration discipline

Migrations are additive and forward-only; a merged migration (including the no-op `V1__baseline.sql`)
is never edited, only superseded by a new file. One concern per file. Index migrations on populated
tables must use `CREATE INDEX CONCURRENTLY` with Flyway transactional execution disabled for that
file. No `CREATE EXTENSION` is used anywhere (UUIDs are app-side; `<@`, `jsonb`, GIN, and `IDENTITY`
are built in).

The founding files:

| Migration | Contents |
|---|---|
| `V2__config_schema.sql` | `CREATE SCHEMA config` + the 9 original config tables (enums, `origin`, config↔config FKs, reference-column content guards, CA rotation columns). |
| `V3__runtime_schema.sql` | `CREATE SCHEMA runtime` + the `is_ip_or_cidr` validator + the 13 original runtime tables (runtime↔runtime FKs, the 1:1 `recording_ref` with RESTRICT, `presence`, generation counters, decision-snapshot columns including names, `audit_event.seq`). |
| `V4__triggers.sql` | `audit_event` append-only + generation-monotonic + presence-nonce-monotonic + recording-write-once triggers. |
| `V5__indexes.sql` | Query-pattern indexes: presence routing, audit search dimensions including GINs on `capabilities` and `node_labels`, a live-session partial index, session lookup, FK columns, `audit_event.seq` UNIQUE, and the partial-unique "one active credential per node" / "one active CA config per kind" constraints. |

## Tables

The table map below is the schema as it stood after `V2`/`V3` (9 config + 14 runtime tables,
including `runtime.idempotency_key` added later by `V22`). Every table added by a later migration is
covered in [Schema history by migration](#schema-history-by-migration) below.

CONFIG (`config` schema, operator-authored desired state, every row has `origin`):

| Table | Purpose |
|---|---|
| `config.node_policy` | Desired labels, connector kind, declared host-pin / host-CA trust refs, stable policy key. |
| `config.dp_rule` | Data-plane grant: identity/node-label/source-IP selectors, principals, ttl, capability set, `allow`\|`deny`. |
| `config.platform_role` | Platform RBAC role: a named set of granular permissions. |
| `config.role_binding` | Binds a subject (user/group) to a `platform_role`, optionally scoped. |
| `config.ca_config` | Per-CA (user/session/host/mtls) backend + key reference (never private material) + algorithm. A kind may have several rows during a rotation overlap; one is `active`. |
| `config.capability_def` | The requestable-capability catalog. |
| `config.jit_policy` | What is JIT-requestable + the 0-3-level approval chain. |
| `config.breakglass_policy` | Break-glass config: recording-strict, alert target, review requirement, auth path. |
| `config.service_account` | Machine-consumer definition (issued credentials are runtime). |

RUNTIME (`runtime` schema, live operational state, no `origin`):

| Table | Purpose |
|---|---|
| `runtime.node` | Live registration, resolved labels, health/status, owning-gateway pointer. |
| `runtime.presence` | `node_id, owning_gateway, gateway_addr, nonce, nonce_id, last_seen`. |
| `runtime.agent_identity` | Agent mTLS identity ref, `generation`, join method, status. |
| `runtime.gateway_identity` | Gateway mTLS identity ref, `generation`, join method, status. |
| `runtime.join_token` | Token hash (never raw), scope, single-use, expiry, `consumed_at`. |
| `runtime.ssh_session` | The `session` entity: identity, node, principal, gateway, access model, times, and the decision snapshot. |
| `runtime.recording_ref` | 1:1 with `ssh_session`, object-store key, encryption-key ref, hash-chain head. |
| `runtime.access_lock` | The `lock` entity: target selector, mode, ttl, reason, created_by. API-only runtime. |
| `runtime.jit_request` | State machine, requester, approver-chain progress, reason, two clocks. |
| `runtime.breakglass_activation` | Principal, reason, alert ref, review status. |
| `runtime.pin` | Pubkey fingerprint, identity, source-cidr, principals, expiry. |
| `runtime.otp` | OTP hash (never raw), identity, allowed principals, source-cidr, expiry, `used`. |
| `runtime.idempotency_key` | (`V22`) The recorded response for one `Idempotency-Key`, scoped to `(principal, method, path)`; bounded by `expires_at`, swept periodically. |
| `runtime.audit_event` | Actor, subject, action, outcome, UTC time, correlation id, `detail` (including config before/after). Append-only, zero FKs. |

## Secrets-at-rest posture

No raw secret is ever stored. `join_token.token_hash` and `otp.otp_hash` store hashes;
`pin.fingerprint` stores a fingerprint; `ca_config.key_reference`, `recording_ref.encryption_key_ref`,
`agent_identity.mtls_identity_ref`, `gateway_identity.mtls_identity_ref`,
`service_account.key_reference`, `node_policy.host_pin_ref`/`host_ca_ref` store references, never key
material. Two enforcement layers: a structural test asserts (via `information_schema`) that no
`token`/`otp`/`secret`/`private_key` column exists on those tables, and a content guard
`CHECK (col NOT LIKE '%PRIVATE KEY%' …)` on the reference columns rejects a PEM private key mistakenly
written into a reference column. An issued service-account `client_secret` is a runtime credential (a
hash in `service_account_credential`), never stored in the config definition.

## Schema history by migration

Each later migration is additive and forward-only; nothing below changes `V2`-`V5`.

### CA signing + carry-forward remediation (`V6`-`V12`)

Added 12 config + 18 runtime = 30 tables total (was 22), plus `audit_event` range partitions.

- Audit range partitioning (`V7`): `runtime.audit_event` recreated as
  `PARTITION BY RANGE (occurred_at)` with composite PK `(id, occurred_at)` (Postgres requires the
  partition key in every unique constraint). `uq_audit_seq` is `UNIQUE (seq, occurred_at)`; a
  `DEFAULT` partition guarantees an insert never fails for a missing range.
  `audit_ensure_partition(date)` / `audit_ensure_partitions(date,int)` create partitions ahead and
  lock each to INSERT/SELECT for `cp_runtime`; `audit_prune_before(timestamptz)` DETACHes and DROPs
  whole partitions past the retention cutoff (never a per-row DELETE). Retention window is
  `operator_settings.audit_retention_days` (default 365). The R2DBC entity keeps a single logical
  `@Id id` (globally unique by UUIDv7); the composite PK is purely a partitioning concern.
- Non-owner runtime DB role (`V11`): creates a non-owner, non-superuser `cp_runtime` role
  (password from the Flyway placeholder `${cpRuntimePassword}`). Grants: CRUD on `config.*` and
  `runtime.*` except `runtime.audit_event` (INSERT/SELECT only, parent and every partition), EXECUTE
  on the helper functions **except `audit_prune_before`**, deliberately withheld so dropping audit
  partitions stays an owner-level action outside the application's reach, SELECT on `flyway_schema_history`; no CREATE/ownership/ALTER/DROP/DISABLE
  TRIGGER. `ALTER DEFAULT PRIVILEGES` auto-grants CRUD on future owner-created tables. R2DBC connects
  as `cp_runtime`; Flyway migrates as the owner.
- Model-gap schema (`V6`, `V8`-`V10`, `V12`):
  - `config.operator_settings` (`V6`): singleton (`singleton boolean UNIQUE CHECK`): KEK ref, default
    CA backend, retention/WORM/OTP/session-limit defaults, the bootstrap self-disable flag (the
    `bootstrap_*` fields are runtime-managed, not operator-editable).
  - `recording_ref` (`V8`) gains `retention_until`, `legal_hold`, `status`, `format`,
    `content_digest` (write-once); `recording_prunable(cutoff)` returns only governance +
    past-retention + non-legal-hold recordings.
  - `runtime.service_account_credential` (`V9`): issued machine credentials (hash/reference only;
    snapshot ref to `config.service_account`).
  - `runtime.device_flow` (`V9`): RFC 8628 state; hashes of the device/user codes;
    `connection_binding` is the 1:1 anti-phishing binding.
  - `runtime.node_host_key` (`V9`): enrollment-anchored host identity (host-CA cert primary, pinned
    key fallback), public material only.
  - `runtime.session_lease` (`V9`): durable per-identity concurrency primitive (unreleased-lease
    count = live sessions).
  - `config.policy_epoch` (`V10`): singleton monotonic epoch (a decrease is trigger-rejected).
  - `config.session_limit_policy` (`V10`): per-identity limit overrides.
  - Status-transition `reason`/`actor` columns (`V10`) on `node`, `agent_identity`,
    `gateway_identity`, and `jit_request` (`decided_by`/`decision_reason`).
  - `runtime.ca_key_material` (`V12`): KEK-wrapped local CA private key (ciphertext only) + public
    material; the KEK is env-sourced, never in the DB; snapshot ref to
    `config.ca_config.key_reference = local:<id>`.
- `jit_request.approvals` shape: stays `jsonb`, documented element shape
  `{approver, level, decision, reason, at}`.
- CA-rotation uniqueness guard (`V13`): a partial unique index allows at most one `incoming` CA
  row per `ca_kind`, closing a race where two concurrent `beginRotation` calls could strand a
  never-expiring key in the trusted set.

### Internal mTLS plane + T4 hardening (`V14`-`V15`)

Added 12 config + 20 runtime = 32 tables total (was 30); no new config table.

- `config.ca_config.ca_kind` gains `mtls` (`V14`, expand/contract on the CHECK).
- `runtime.ca_key_material` gains a nullable `ca_certificate bytea` (`V14`): the self-signed X.509
  CA cert (DER) for the `mtls` CA, NULL for SSH CAs. The write-once trigger is extended to cover it.
- Two single-use token tables (`V14`), both hash-only with a `@Version`-guarded consume:
  - `runtime.gateway_enrollment_token`: operator-provisioned bootstrap credential, scoped to one
    `gateway_name`, single-use (`consumed_at`), 10-minute TTL (`expires_at`).
  - `runtime.session_signing_token`: per-RPC session-bound authority for
    `SignSessionCertificate`, bound to `{gateway_id, session_id, node_id, principal, capabilities,
    exp}`, single-use (`used`/`used_at`), 120 s TTL; `capabilities` CHECK-constrained to the SSH
    capability set, `source_address` CIDR/IP-validated.
- T4 hardening (`V15`):
  - `runtime.gateway_identity` gains `prev_fingerprint text` (nullable): renew/sign RPCs pin the
    presented client cert's SHA-256 fingerprint to `{current, previous}`, tolerating the renew-ahead
    overlap. `renew` records the outgoing fingerprint; NULL for a freshly-enrolled (generation 0)
    identity.
  - Both single-use token tables have DELETE revoked from `cp_runtime` (`V15`); a row is consumed by
    UPDATE only, never erased.

### Authorization (no migration)

No migration; next free version stays `V16`. Selector shapes the evaluator now enforces:

- `dp_rule.identity_selector`: `{"identities": [..], "groups": [..], "all": <bool>}`. An absent or
  empty selector selects no one.
- `dp_rule.node_label_selector`: `{"<label-key>": <condition>, ...}` where a condition is
  `{"op": "eq"|"glob"|"in"|"regex", "value": "..", "values": [..]}` or an array of conditions. AND
  across keys, OR within a key. `regex` is anchored RE2/J (linear-time, no ReDoS); `null`/`{}` matches
  all nodes; a key the node lacks fails that key.
- `dp_rule.source_ip_condition`: `{"permit_cidrs": [..], "deny_cidrs": [..]}`. A deny-only reducer:
  applies only if the source is inside `permit_cidrs` (when present) and outside every `deny_cidrs`.
  An unknown source with any restriction present fails closed (suppressed, never granted).
- `access_lock.target_selector`: `{"identity": ".."}` / `{"node_id": ".."}` / `{"principal": ".."}`
  / `{"node_label": {"key":..,"value":..}}`: any facet matching is a match. An empty or
  uninterpretable target matches (global lockdown, deny wins).
- `role_binding.scope`: `{"node_labels": {..}, "users": [..], "time": {"not_before": "<ISO>",
  "not_after": "<ISO>"}}`. Each present facet must be satisfied (AND); absent is unrestricted;
  `null`/`{}` is an unrestricted binding.

Runtime writes the decision produces: `ssh_session` gets the decision snapshot on allow
(`access_model`, resolved `principal`, `capabilities`, `matched_rule_id`+`matched_rule_name`,
`policy_epoch`, `grant_expiry`), keyed by the Gateway-allocated `session_id`.
`session_signing_token` is minted only on allow (deny/lock ⇒ none). The `ssh_session` insert, the
allow audit event, and the token mint are one transaction. Every data-plane and platform decision is
recorded to `audit_event`. The decision-context signer is a fresh ECDSA P-256 keypair minted in-memory once per
boot and certified as a `CONTEXT_SIGNER` leaf from the internal mTLS CA: nothing is persisted, no
schema is needed.

### Authentication (`V16`)

Added 12 config + 23 runtime = 35 tables total (was 32); no new config table.

- `runtime.oidc_login`: transient auth-code + PKCE relying-party state, one row per browser login,
  single-use (`consumed_at`). Stores only the SHA-256 of the opaque `state` (`state_hash`, UNIQUE);
  the PKCE `code_verifier` and OIDC `nonce` are never stored, only derived server-side and recomputed
  at the callback. `purpose='device'` links the `device_flow` a login approves.
- `runtime.auth_rate_limit`: durable fixed-window counters keyed by an opaque `bucket` (for example
  `otp:verify:<ip>`, `token:<clientId>`); one atomic upsert per event
  (`ON CONFLICT (bucket) DO UPDATE`).
- `runtime.consumed_assertion`: single-use guard for `private_key_jwt` client-assertion `jti` (hash
  only, with the assertion's own `not_after`); `INSERT ... ON CONFLICT (jti_hash) DO NOTHING`. A
  periodic prune drops rows past `not_after`.
- `runtime.device_flow` (ALTER) gains `approver_source_ip`, `approver_context jsonb`, and
  `source_context_match boolean`: the approving browser's source context correlated with the SSH
  source IP. A mismatch is flagged and audited, and denies only when
  `sessionlayer.oidc.device.enforce-source-match` is on (default off).

No raw secret is persisted: OTP → `otp_hash`; device/user codes → `device_code_hash`/`user_code_hash`;
auth-code `state` → `state_hash`; machine `client_secret` → SHA-256; a `private_key_jwt` public key →
base64 DER in `service_account_credential.secret_hash`; an mTLS credential → the cert SHA-256
fingerprint; the printed-once bootstrap credential → `operator_settings.bootstrap_credential_hash`.

### Outer and inner SSH legs (no migration)

Neither adds a migration (next free version stays `V17`). The inner leg reads existing inventory
(`runtime.node.connector_kind`/`address`, `runtime.node_host_key`) to fill the host-identity anchors;
no new tables or columns.

### Session recorder & WORM (`V17`)

- `config.operator_settings` gains the customer encryption key and recording policy. The CP holds
  only the public half:
  - `recording_customer_public_key bytea`: DER SubjectPublicKeyInfo. Nullable; NULL makes
    `BeginRecording` fail closed (recording is mandatory).
  - `recording_key_seal_algorithm text NOT NULL DEFAULT 'ecies_p256'` (CHECK
    `ecies_p256 | rsa_oaep_sha256`). The column shape allows either, and the API accepts only
    `ecies_p256` with an EC key on P-256, per the note under [Enums](#enums). Generate a P-256
    keypair; an RSA one is a `422`.
  - `recording_key_ref text`: persisted into `recording_ref.encryption_key_ref`; defaults to
    `customer-recording-key` when unset.
  - `recording_retention_days int NOT NULL DEFAULT 365` (`>= 1`), floored at 1.
  - `recording_strict_default boolean NOT NULL DEFAULT true`: unused. No code path reads it,
    recording is unconditionally strict and fail-closed, and the operator-settings API does not
    expose it.
- `runtime.recording_token`: the second single-use, session-bound token (mirrors
  `session_signing_token`), minted at `Authorize` ALLOW alongside the signing token, bound to
  `{gateway_id, session_id, node_id, principal, exp}`; authorizes exactly one
  `Recording.BeginRecording` call. Hash only; consumed via `used` under the `@Version` lock; DELETE
  revoked from `cp_runtime`.
- `recording_ref` is now written by the CP: `BeginRecording` inserts `object_key` /
  `encryption_key_ref` / `worm_mode` / `retention_until` (status `recording`); `FinalizeRecording`
  fills `hash_chain_head` / `content_digest` / `size_bytes` / `status`
  (`finalized`|`truncated`|`failed`): a NULL→value transition the write-once trigger permits once.
- `audit_event`'s hash chain is now populated: `record_hash = SHA-256(prev_hash ‖
  canonical(event))`, `prev_hash` = the previous row's `record_hash` in `seq` order (a fixed
  `GENESIS` value for the first row). Each write serializes on a transaction-scoped advisory lock
  (`pg_advisory_xact_lock`) inside the audit transaction. A partial index `idx_audit_chain_head` on
  `(seq DESC) WHERE record_hash IS NOT NULL` (`V17`) keeps the chain-head read O(1).
- The recording upload credential is issued at upload time by a separate `RequestUpload` RPC (not at
  `BeginRecording`): a short-lived (default 120 s), single-object presigned PUT to a WORM bucket with
  object-lock enabled; the lock mode and retain-until are baked into the signature as
  `required_headers` the Gateway must replay verbatim.

### Per-channel re-eval & lock push (`V18`)

No new table (the lock is the existing `runtime.access_lock`).

- `platform_role.permissions` CHECK widened to admit `lock:read` and `lock:write`.
- `access_lock.target_selector` gains the canonical plural shape (`identities` / `groups` /
  `node_ids` / `principals` / `node_labels` as `"key=value"` / `all`), OR-matched against the older
  singular back-compat form (`identity`/`group`/`node_id`/`principal`/`node_label{key,value}`). An
  empty/unrecognized target still fails closed; ingest validation requires an explicit `all:true` for
  a fleet-wide lock.

### Agent join & renewable identity (`V19`)

- `runtime.agent_identity` gains a nullable `prev_fingerprint text`: the mirror of `V15`'s
  `gateway_identity.prev_fingerprint`. NULL for a freshly-enrolled (generation 0) identity; the
  previous generation's SHA-256 cert fingerprint thereafter.
- No new tables: `join_token` backs token join; `agent_identity` holds the per-node mTLS identity ref
  plus `generation`/`join_method`/`status` (one `active` per node, partial unique index); a
  generation-mismatch clone auto-locks by flipping `agent_identity.status='locked'` and inserting a
  strict, no-TTL `access_lock` covering the node.

### Access models: JIT, break-glass, FIDO2 (`V20`)

- `runtime.breakglass_credential`: a registered FIDO2 `sk-ecdsa` public key. Keyed by SHA-256
  `key_fingerprint` (UNIQUE); holds the OpenSSH `sk-ecdsa` wire pubkey (public material only),
  `sk_application`, `identity`, `allowed_principals`, optional `node_selector` scope, optional
  `expires_at`, `revoked_at`. No private key at rest.
- `runtime.breakglass_offline_code`: a pre-issued single-use code. `code_hash` only (UNIQUE), ≥128-bit
  entropy, `identity`, `allowed_principals`, optional `node_selector`/`source_cidr`, `expires_at`,
  atomic single-use via `used`, `revoked_at` for batch invalidation.
- `runtime.breakglass_token`: the single-use authority minted on a successful break-glass RESOLVE and
  consumed at `Authorize`. Mirrors `recording_token`: `token_hash` only, bound to `{gateway_id,
  identity, node_id, source_address, exp}` plus the carried `allowed_principals`.
- `runtime.breakglass_activation` (ALTER) gains `identity`, `source_ip`, `target_node_id` (snapshot,
  no FK), `credential_ref`.
- `platform_role.permissions` CHECK widened to admit `breakglass:manage`.
- The two single-use stores (`breakglass_offline_code`, `breakglass_token`) have DELETE revoked;
  `breakglass_credential` keeps DELETE (an admin may remove a registration outright, alongside the
  soft `revoked_at`).
- JIT and break-glass reach the wire via the existing decision path: a JIT grant is a time-boxed
  synthetic allow (so deny-overrides and the lock still apply); break-glass raises an activation and
  alert before the decision, then the allow is evaluated subject to the lock.
  `DecisionContext.access_model` is signed and emitted only when non-standing. JIT-revoke /
  break-glass-abort is expressed as a lock; no new revocation entity.

### Host addressing & node lifecycle (no migration)

Uses only existing columns: `node.status` (`pending`/`active`/`quarantined`/`removed`), `node.health`,
`status_reason`/`status_changed_by`/`status_changed_at`, `node_host_key`, `access_lock`, and the
`agent_identity` generation guard.

- Name→id resolution: `AuthorizeRequest.node_name` resolves to `runtime.node.id` via
  `NodeRepository.findByName`, server-side and authoritative; a client-supplied `node_id` is ignored
  when a name is present.
- Enroll (agentless) = insert `runtime.node` (`connector_kind='agentless'`, `status='active'` or
  `'pending'` when approval is on) + a `runtime.node_host_key` row (`source='host_ca'` or
  `source='pinned_key'`, never TOFU).
- Quarantine = flip `node.status='quarantined'` + insert a node-targeting `access_lock` (strict,
  `{"node_ids":[…]}`); release deletes the lock and flips back to `active`.
- Remove = flip `node.status='removed'` (soft; history preserved via the `ON DELETE SET NULL` FKs)
  and, for an agent node, revoke the credential (flip `agent_identity.status` off `active` plus a
  covering lock).
- The Gateway's ProxyJump outer host certificate is signed from the existing `host` SSH CA; nothing is
  persisted.

### Audit search, recording replay/export, retention (`V23`)

- `platform_role.permissions` CHECK widened to add `recording:delete`.
- `recording_ref` gains `pruned_at`, `delete_mode` (`retention`|`governance`), `deleted_by`,
  `legal_hold_reason`, all nullable and mutable (the write-once trigger still guards only
  `session_id`/`object_key`/`encryption_key_ref`/`hash_chain_head`/`content_digest`). The provenance
  row is never deleted: retention prune and governance delete erase the encrypted object and mark the
  row, so the audit trail that a recording existed (and was expired or erased, by whom) survives.
  `recording_prunable(cutoff)` is refreshed to also skip already-pruned rows; it never returns
  compliance-mode or legal-held recordings.
- No new tables. Replay/export return short-lived signed GET URLs to the still-encrypted object; the
  CP holds only the customer public key and cannot decrypt.

### Recording version pin, index-only tuning, agent-renewal receipts (`V24`-`V27`)

No new config tables; one new runtime table (`V27`).

- Recording replay/export version pin (`V24`): `recording_ref` gains `object_version_id text`
  (nullable), added to the same write-once guard as `hash_chain_head`/`content_digest`. Object Lock on
  a versioned bucket protects one object version, not the key: a later `PUT` to the same key becomes
  the version an unversioned GET returns, so a compromised CP (holds the customer public key and could
  seal a forgery) or Gateway could shadow a finalized recording with a re-sealed object at the same
  key. Recording the version id the Gateway actually `PUT` and pinning replay/export to it makes the
  finalized bytes the only ones ever served; a DB superuser rewriting the column is the same residual
  the deferred external Merkle anchor (`FR-AUD-10`) is meant to address.
- `ix_ssh_session_active_identity` (`V25`): partial index on `ssh_session (identity) WHERE ended_at IS
  NULL`, backing the config-API session-listing `activeOnly` filter by identity; `idx_session_live`
  (`V5`) is keyed on `node_id` and doesn't serve this path. No new table.
- `idx_jit_request_usable` (`V26`): covering partial index on
  `jit_request (requester, target_node_id, principal, grant_expires_at) WHERE state IN ('APPROVED',
  'ACTIVE')`, backing `JitRequestRepository.findUsableGrant`: Authorize now looks up a usable JIT
  grant unconditionally on every connect rather than only when standing access fails, so the lookup
  needs a direct index instead of a per-requester scan. No new table.
- `runtime.agent_renewal_receipt` (`V27`): idempotent-retry receipt for `RenewAgentIdentity`. A
  lost/late renew response makes the Agent retry with the same (now-stale) generation after the CP
  already committed the renewal; without a receipt, that retry is indistinguishable from a genuine
  clone racing the old generation and gets auto-locked (permanent outage plus a false security alert).
  Keyed `UNIQUE (agent_id, prior_generation, csr_public_key_hash)`: a real clone cannot reproduce the
  CSR keypair, so a benign self-retry can replay the already-issued `certificate`/`ca_certificate`
  (public material, not secret) while clone detection stays intact for a different key. RUNTIME,
  mirrors `runtime.idempotency_key` (`V22`): no `origin`, bounded by `expires_at`; `cp_runtime` gets
  CRUD automatically via `V11`'s `ALTER DEFAULT PRIVILEGES`, no explicit `GRANT` needed.

### Gateway enrollment and operator-settings permissions (`V28`-`V29`)

No new tables, and no new columns. Both are CHECK widenings plus one data back-fill.

- `platform_role.permissions` gains `gateway:enroll` (`V28`), then `gateway:remove` and
  `recording:key-manage` (`V29`), bringing the vocabulary to the twenty names listed under
  [Enums](#enums). `gateway:enroll` gates the Gateway enrollment-token API and the internal mTLS
  trust-anchor export, so installing a Gateway needs an API credential rather than raw `psql`. It is
  deliberately not `ca:manage`: exporting a public trust anchor is not CA administration.
  `gateway:remove` is separated from `gateway:enroll` exactly as `node:remove` is from
  `node:enroll`, and `recording:key-manage` is separated from `settings:write` because its holder
  can point future recordings at a key whose private half they control.
- The back-fill (`V29`). `BootstrapService.ensureAdminRole()` creates `platform-admin` only when it
  is absent, and the bootstrap flow returns early once `bootstrap_completed` is set, so an
  already-bootstrapped deployment's admin role is never revisited. Every widening since `V18` had
  therefore admitted a verb without granting it, and an upgraded deployment's platform admin
  silently lacked it. `V29` appends every missing member once, scoped to `origin = 'default'` so a
  role an operator has curated through `/v1/roles` is left alone. It is idempotent: a role already
  holding the whole vocabulary is not matched.
- `ca_config.algorithm` gains `ecdsa-p521` (`V29`). `CaKeyType` has always implemented P-521; the
  CHECK admitted only P-256 and P-384, so a working curve was unreachable. The CHECK is widened and
  not narrowed, so `ed25519`/`rsa-2048`/`rsa-4096` remain storable and unusable, per the note under
  [Enums](#enums).

This brings the schema to 12 config + 29 runtime = 41 tables total, recounted from every
`CREATE TABLE` across `V2`-`V29`. The last running total stated in this log (35, at `V16`) had gone
stale: `V17` (`recording_token`), `V20` (three break-glass tables), and `V22` (`idempotency_key`)
each added a runtime table without a following total.

Two things make a naive `grep -c 'CREATE TABLE'` overcount, both worth knowing before you
"correct" the number back to 30: `runtime.audit_event_default` is a `PARTITION OF`, not a table in
its own right, and `runtime.audit_event` is created twice, in `V3` and again in `V7`, which drops
and rebuilds it as partitioned.

### Azure Key Vault CA backend (`V30`)

No new table. `runtime.ca_key_material` had assumed a `local`-backend row unconditionally:
`wrapped_key`/`iv`/`kek_reference` were each individually `NOT NULL`/CHECKed, with nothing tying
the three together as one shape. A CA whose key lives in Key Vault has no wrapped private key at
all, so `V30` adds `key_location` (`local_kek`\|`external`, default `local_kek`) and replaces the
three column-level CHECKs with one table-level CHECK keyed on it: `local_kek` requires exactly the
`V12` shape, now enforced jointly rather than column-by-column; `external` requires all three
`NULL`. `public_key` stays `NOT NULL` for both — an external CA's public key is resolved from the
key service at adoption and persisted, which is what keeps `CaPublicKeyService`,
`CaRotationService.trustedCaKeys` and `LocalCaFactory.publicAuthorizedKey` working unchanged
regardless of `key_location`. The write-once trigger (`V12`) gains `key_location` as a fourth
immutable column.

## Next

- [API](api.md)
- [Control Plane configuration](config-control-plane.md)
- [Audit events](audit-events.md)
- [Certificate authorities](../admin-guides/certificate-authorities.md)
