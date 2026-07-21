# Install the Control Plane

When you finish this page you have a running Control Plane: migrations applied,
the three certificate authorities provisioned, the mTLS gRPC plane listening for
Gateways, and a first admin ready to log in.

Prerequisites:

- [ ] PostgreSQL 17 reachable, with a database and an owner role for SessionLayer
- [ ] Java 25 runtime on the host (or use a container)
- [ ] the [ControlPlane-API](https://github.com/SessionLayer/ControlPlane-API)
      source checkout (releases are built from source)

## Build the jar

```bash
git clone https://github.com/SessionLayer/ControlPlane-API.git
cd ControlPlane-API
./mvnw -DskipTests package
ls target/controlplane-*.jar
```

## Configure the database — two roles, on purpose

The Control Plane connects to Postgres twice, as two different roles:

- **Flyway migrations** run once at startup as the **owner** role
  (`spring.flyway.*`) — it creates schemas, tables, triggers, and the restricted
  runtime role.
- **Runtime traffic** uses the **restricted `cp_runtime` role**
  (`spring.r2dbc.*`) — it cannot alter tables, cannot disable the audit
  append-only trigger, and cannot update or delete audit rows. A compromised
  application credential is contained by the database itself.

Set the runtime password **before first boot**, in both places, to the same
value:

```properties
spring.flyway.url=jdbc:postgresql://db.example.com:5432/sessionlayer
spring.flyway.user=sessionlayer
spring.flyway.password=<owner-password>
# Substituted into ALTER ROLE on the FIRST migration only — set it now, not later.
spring.flyway.placeholders.cpRuntimePassword=<runtime-password>

spring.r2dbc.url=r2dbc:postgresql://db.example.com:5432/sessionlayer
spring.r2dbc.username=cp_runtime
spring.r2dbc.password=<runtime-password>
```

> **Warning:** the runtime password placeholder is applied only on the first
> migration and must be alphanumeric (it is substituted into an
> `ALTER ROLE … PASSWORD` literal). To rotate later, run
> `ALTER ROLE cp_runtime PASSWORD '…'` in Postgres and update
> `spring.r2dbc.password` in lockstep — changing the placeholder afterwards
> rotates nothing.

## Set the CA key-encryption key

On first boot the Control Plane generates its three SSH CAs and the internal
mTLS CA. With the default **local** CA backend the private keys are
envelope-encrypted at rest under a key-encryption key you provide:

```properties
# 32 bytes, base64. Generate with: openssl rand -base64 32
sessionlayer.ca.local.kek-base64=<your-kek>
```

> **Warning:** if you set no KEK the Control Plane **refuses to start** rather
> than silently encrypting CA keys under a public dev constant. The escape
> hatch, `sessionlayer.ca.local.allow-dev-kek=true`, is for development only.
> For production, prefer moving the CAs to Vault, AWS KMS, or Azure Key Vault
> entirely — see [Certificate authorities](../admin-guides/certificate-authorities.md).

## Run it

```bash
java -jar target/controlplane-*.jar \
  --spring.config.additional-location=file:/etc/sessionlayer/controlplane.properties
```

First boot, in order: Flyway migrates the empty database, the CA provisioning
job idempotently creates the three SSH CAs plus the internal mTLS CA, and the
first-admin bootstrap arms itself. Startup is unattended — the only external
dependency is Postgres.

Check it:

```bash
curl -s http://localhost:8080/v1/healthz
curl -s http://localhost:8080/v1/version
```

## Claim the first admin

An unconfigured system has empty RBAC and would deny everyone, so a one-time
bootstrap provisions the initial platform admin. Pick one of two paths:

- **Config-named OIDC subject** — set
  `sessionlayer.bootstrap.admin-subject=<oidc-subject>` (and
  `sessionlayer.bootstrap.admin-subject-kind=user|group`) before first boot;
  that identity is the first platform admin.
- **Printed-once credential** — with no subject configured, the Control Plane
  prints a bootstrap credential to its log exactly once; claiming it provisions
  the admin.

Either way the bootstrap **self-disables** once a platform admin exists, and
its use is audited.

## The two network surfaces

| Listener | Default | Who connects |
|---|---|---|
| REST API + OIDC pages | `:8080` (`server.port`) | admins, users, the Dashboard, machine clients |
| mTLS gRPC plane | `:9090` built-in default; set `sessionlayer.mtls.server.port=9443` | Gateways and Agents only |

All examples in this documentation put the gRPC plane on **9443** — it is what
the Gateway's `cp_mtls_endpoint` and the Agent's `--cp-endpoint` default to and
what the shipped deployment manifests use — so set
`sessionlayer.mtls.server.port=9443` (or map a `9443` Service port onto the
container). The built-in default is `9090`; either works if both sides agree.

Run the REST surface behind your TLS-terminating L7 load balancer, on HTTPS
only. The Control Plane honors `X-Forwarded-*` headers for client IPs
(`server.forward-headers-strategy=framework`), so the proxy in front of it
**must strip client-supplied forwarding headers** — source IP is deny-only
evidence, so a spoof can only over-restrict, but keep the chain clean.

The gRPC plane needs no external load balancer TLS: the Control Plane mints its
own server certificate from the internal mTLS CA at runtime. Set
`sessionlayer.mtls.server.hostnames` to the DNS names Gateways will dial, so
they land in the certificate's SANs.

## Recording store

Point the Control Plane at your WORM bucket (it issues presigned PUTs; recording
bytes never pass through it):

```properties
sessionlayer.recording.worm.endpoint=https://s3.example.com
sessionlayer.recording.worm.bucket=sessionlayer-recordings
sessionlayer.recording.worm.region=us-east-1
# Blank access-key = the AWS default credential chain / IAM role.
sessionlayer.recording.worm.access-key=
sessionlayer.recording.worm.secret-key=
```

The customer recording public key, retention, and compliance-vs-governance mode
are operator settings in the database, not properties — configure them in
[Session recording](../admin-guides/session-recording.md).

## Before production

Work through the [production hardening checklist](../security/hardening.md) —
it covers the KMS-backed CAs, Postgres HA with synchronous replication for the
authz/audit tables, HTTPS origins, and the session-limit default (unset means
**unlimited concurrent sessions**; the Control Plane warns about this at boot).

## Next

- [Install the Gateway](gateway.md)
- [Enroll nodes](../admin-guides/nodes.md)
- [Production hardening](../security/hardening.md)
- [Control Plane configuration reference](../reference/config-control-plane.md)
