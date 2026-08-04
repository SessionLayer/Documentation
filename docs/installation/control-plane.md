# Install the Control Plane

SessionLayer's Control Plane is the platform's single source of truth: a
Java process that owns Postgres for identity, RBAC, locks, and audit, and
exposes it to Gateways and Agents over mTLS gRPC and to admins over REST.
Working through this page takes a bare checkout to migrations applied, all
three SSH certificate authorities and the internal mTLS CA provisioned, and
a first admin ready to log in.

Prerequisites:

- [ ] PostgreSQL 17 reachable, with a database and an owner role for SessionLayer
- [ ] Java 25 to run the jar directly, or Docker/Kubernetes to run the
      container image instead
- [ ] a [ControlPlane](https://github.com/SessionLayer/ControlPlane) checkout
      at the tag you are deploying, for the chart, the manifests and the
      systemd unit, none of which are distributed separately

## Pick a deployment model

| | Container (Kubernetes) | Bare-metal / VM (systemd) |
|---|---|---|
| Assets | `deploy/helm/sessionlayer-controlplane/`, or `deploy/kubernetes/control-plane.yaml` | `deploy/systemd/sessionlayer-control-plane.service` |
| Identity | non-root (uid 65532), read-only rootfs | `DynamicUser=yes`: no privileged port to bind, no local state to keep a stable UID for |
| Config | a ConfigMap + a Secret, both plain `SPRING_*`/`SESSIONLAYER_*` env vars | one `EnvironmentFile` |
| Egress control | `deploy/kubernetes/networkpolicy.yaml` | host firewall |

Unlike the Gateway, the Control Plane binds no privileged port and keeps no
local persistent state (every secret lives in Postgres or the mounted config
above), so there is no privilege-drop-after-bind step and no data volume to
provision either way.

## Get it

```bash
docker pull ghcr.io/sessionlayer/controlplane:v0.0.2
```

`v0.0.2` is the release tag; substitute the one you are installing. There is no
`:latest`. The image is a `linux/amd64` + `linux/arm64` index carrying Adoptium's
Java 25 JRE on a distroless base, so there is no shell, no package manager and
no JDK tooling in it. `USER` is a numeric 65532, which is what lets Kubernetes
`runAsNonRoot` enforce it without an `/etc/passwd` lookup, and `/tmp` is the
only path the process writes.

> **Note:** the image compiles its own jar from source in a build stage. That
> jar is not the signed artifact attached to the GitHub Release, and no
> reproducibility gate compares the two. What covers the image is the image's
> own signature, provenance and SBOM
> ([Supply chain](../security/supply-chain.md)).

Verify it before you run it. The signature and the provenance sit in the
registry beside the image, so this needs nothing downloaded first:

```bash
DIGEST=$(docker buildx imagetools inspect ghcr.io/sessionlayer/controlplane:v0.0.2 \
  --format '{{json .Manifest}}' | jq -r .digest)

cosign verify "ghcr.io/sessionlayer/controlplane@$DIGEST" \
  --certificate-identity "https://github.com/SessionLayer/ControlPlane/.github/workflows/release.yml@refs/tags/v0.0.2" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"

gh attestation verify "oci://ghcr.io/sessionlayer/controlplane@$DIGEST" \
  --repo SessionLayer/ControlPlane
```

Deploy `$DIGEST`, not the tag. A registry tag can be re-pushed to different
bytes and every manifest naming it looks unchanged.
[Supply chain](../security/supply-chain.md) covers reading the image's SBOM and
the rest of the release evidence.

To run the jar directly, or to build either artifact yourself:

```bash
git clone https://github.com/SessionLayer/ControlPlane.git
cd ControlPlane
./mvnw -DskipTests package
ls target/controlplane-*.jar

# or, to build the container image instead:
docker build -f deploy/Dockerfile -t sessionlayer-controlplane .
```

> **Note:** building from a clone means you run whatever the checkout
> contains. For anything beyond evaluation, build from a reviewed, pinned
> commit or tag, not a moving branch. [Supply chain](../security/supply-chain.md)
> covers verifying released artifacts.

## Configure the database: two roles, on purpose

The Control Plane connects to Postgres twice, as two different roles:

- Flyway migrations run once at startup as the owner role
  (`spring.flyway.*`). It creates schemas, tables, triggers, and the
  restricted runtime role.
- Runtime traffic uses the restricted `cp_runtime` role (`spring.r2dbc.*`).
  It cannot alter tables, cannot disable the audit append-only trigger, and
  cannot update or delete audit rows. A compromised application credential is
  contained by the database itself.

Set the runtime password before first boot, in both places, to the same
value. Generate one with `openssl rand -hex 24` (a hex string is alphanumeric,
which the runtime password must be):

```properties
spring.flyway.url=jdbc:postgresql://db.example.com:5432/sessionlayer
spring.flyway.user=sessionlayer
spring.flyway.password=<owner-password>
# Substituted into ALTER ROLE on the FIRST migration only. Set it now, not later.
spring.flyway.placeholders.cpRuntimePassword=<runtime-password>

spring.r2dbc.url=r2dbc:postgresql://db.example.com:5432/sessionlayer
spring.r2dbc.username=cp_runtime
spring.r2dbc.password=<runtime-password>

# The mTLS gRPC plane Gateways and Agents dial. The built-in default is 9090;
# 9443 is what their endpoint defaults expect. See "The two network surfaces".
sessionlayer.mtls.server.port=9443
```

> **Warning:** the runtime password placeholder is applied only on the first
> migration and must be alphanumeric (it is substituted into an
> `ALTER ROLE … PASSWORD` literal). To rotate later, run
> `ALTER ROLE cp_runtime PASSWORD '…'` in Postgres and update
> `spring.r2dbc.password` in lockstep. Changing the placeholder afterwards
> rotates nothing.

`spring.flyway.placeholders.cpRuntimePassword` is a `Map` key. Spring's general
relaxed-binding documentation warns that Map keys sourced from environment
variables get lower-cased, which would suggest
`SPRING_FLYWAY_PLACEHOLDERS_CPRUNTIMEPASSWORD` can only ever address
`cpruntimepassword`. Verified against this exact env var name on Spring Boot
4.1.0, it binds correctly: setting it as a plain environment variable,
alongside `SPRING_R2DBC_PASSWORD`, is safe.

## Set the CA key-encryption key

On first boot the Control Plane generates its three SSH CAs and the internal
mTLS CA. With the default local CA backend the private keys are
envelope-encrypted at rest under a key-encryption key you provide:

```properties
# 32 bytes, base64. Generate with: openssl rand -base64 32
sessionlayer.ca.local.kek-base64=<your-kek>
```

> **Warning:** if you set no KEK the Control Plane refuses to start, rather
> than silently encrypting CA keys under a public dev constant. The escape
> hatch, `sessionlayer.ca.local.allow-dev-kek=true`, is for development only.
> Every CA starts on `local` at cold start, so set a real KEK regardless of
> what you do afterward. The internal mTLS CA cannot move off `local` at all,
> so this KEK always protects it; the three SSH CAs (`user`/`session`/`host`)
> can later be adopted onto Azure Key Vault or AWS KMS, at which point their
> keys leave the database entirely. Take the KEK from your secrets manager and
> keep it out of the database's backup path. See
> [Certificate authorities](../admin-guides/certificate-authorities.md).

## Run it

### Plain jar (evaluation)

```bash
java -jar target/controlplane-*.jar \
  --spring.config.additional-location=file:/etc/sessionlayer/controlplane.properties
```

### Docker

```bash
docker run -d --name sessionlayer-controlplane \
  -e SPRING_R2DBC_URL=r2dbc:postgresql://db.example.com:5432/sessionlayer \
  -e SPRING_R2DBC_USERNAME=cp_runtime \
  -e SPRING_R2DBC_PASSWORD=<runtime-password> \
  -e SPRING_FLYWAY_URL=jdbc:postgresql://db.example.com:5432/sessionlayer \
  -e SPRING_FLYWAY_USER=sessionlayer \
  -e SPRING_FLYWAY_PASSWORD=<owner-password> \
  -e SPRING_FLYWAY_PLACEHOLDERS_CPRUNTIMEPASSWORD=<runtime-password> \
  -e SESSIONLAYER_CA_LOCAL_KEK_BASE64=<your-kek> \
  -e SESSIONLAYER_MTLS_SERVER_PORT=9443 \
  --read-only --tmpfs /tmp:rw,exec,nosuid,size=256m \
  -p 8080:8080 -p 9443:9443 \
  "ghcr.io/sessionlayer/controlplane@$DIGEST"
```

The image's `EXPOSE` line names `9443`, but nothing in it sets the port, so
the environment variable above is what actually moves the listener off the
built-in `9090`. Drop it and the published `9443` reaches nothing.

> **Note:** `--tmpfs /tmp` alone defaults to `noexec`, which blocks Netty's
> native epoll transport from unpacking its library there; the process still
> starts (it falls back to NIO with a log warning), but pass `exec` to keep
> the native transport available.

The image bakes in no `JAVA_TOOL_OPTIONS`, because heap and GC belong to
whatever knows the memory limit. Wherever you set one, set the heap with it:
`-e JAVA_TOOL_OPTIONS=-XX:MaxRAMPercentage=75.0` alongside a `--memory` cap.
The JVM's own default of 25% undersizes the heap for a WebFlux, gRPC and R2DBC
workload; the chart's `java.toolOptions` does this for you.

### Kubernetes, with Helm

`deploy/helm/sessionlayer-controlplane` renders a Deployment, a Service, a
ConfigMap, a ServiceAccount, a PodDisruptionBudget and a NetworkPolicy. It
creates no Secret, so make yours first, from the key list in
`deploy/kubernetes/secret.example.yaml`:

```bash
kubectl create namespace sessionlayer
kubectl -n sessionlayer apply -f my-controlplane-secrets.yaml

helm install cp deploy/helm/sessionlayer-controlplane \
  --namespace sessionlayer \
  --set secrets.existingSecret=sessionlayer-controlplane-secrets \
  --set image.digest="$DIGEST" \
  --set recording.worm.endpoint=https://worm.example.com \
  --set oidc.issuer=https://idp.example.com \
  --set oidc.clientId=sessionlayer-controlplane \
  --set oidc.redirectUri=https://cp.example.com/v1/auth/callback
```

Replace the `worm` and `idp` hosts with your object store and identity
provider. For an OTP, pins or machine-identity-only deployment, drop the three
`oidc.*` values and set `oidc.enabled=false` instead.

The values that decide whether the install is a safe one:

| Value | Default | Why it decides |
|---|---|---|
| `secrets.existingSecret` | `""` | Names the Secret carrying the two database passwords, the CA key-encryption key, the OIDC client secret and state HMAC key, and the object-store credentials. Rendering fails without it, naming every key. |
| `recording.worm.endpoint` | `""` | Required. The application's own default points at a development MinIO with a well-known credential. |
| `image.digest` | `""` | Wins over `image.tag`. Pin the digest you verified above. |
| `networkPolicy.enabled` | `true` | Default-deny in both directions. `wormCidrs` and `oidcCidrs` start empty, so egress to your object store and IdP is denied until you name the ranges. |
| `podDisruptionBudget.minAvailable` | `1` | Rendering fails when this is not below `replicaCount`, because such a budget refuses every voluntary eviction and hangs a node drain. |
| `serviceAccount.automountServiceAccountToken` | `false` | The Control Plane never calls the Kubernetes API, so a projected token is credential surface with no purpose. |

No value turns on the development key-encryption key. Doing that takes a
deliberate `extraEnv` entry, which is the point: a chart that defaulted one so
the install "worked" would have wrapped every certificate authority private key
under a public constant.

The chart runs no migration Job and no init container. Flyway runs inside
Spring's context refresh, and `/actuator/health/readiness` does not report
ready until it and both bootstrap runners have finished, so the readiness probe
is what gates traffic on the migration. `probes.startup.failureThreshold` of 60
allows five minutes for it, which also covers a second replica waiting out
Flyway's database-level lock during a rolling update. Lowering it is how a slow
first migration becomes a restart loop.

The chart's own `README.md` documents every value.
[Deploy with Helm](helm.md) covers what all four charts have in common, and
the static-validation-only status they ship with.

### Kubernetes, plain manifests

```bash
kubectl create namespace sessionlayer
kubectl apply -n sessionlayer -f deploy/kubernetes/networkpolicy.yaml
# fill in deploy/kubernetes/secret.example.yaml with real values first:
kubectl apply -n sessionlayer -f deploy/kubernetes/secret.example.yaml
kubectl apply -n sessionlayer -f deploy/kubernetes/control-plane.yaml
```

`deploy/kubernetes/control-plane.yaml` ships a Deployment (2 replicas), a
Service named `controlplane`, a ConfigMap, and a PodDisruptionBudget. Its
readiness probe polls `/actuator/health/readiness`, which does not report
ready until Flyway and both startup jobs (CA provisioning, first-admin
bootstrap) have finished, so a load balancer never routes to a pod
mid-migration. Running two replicas through a rolling update can run Flyway
from two pods at once; this is safe by construction, since Flyway takes a
Postgres-level lock before migrating, so the second pod's Flyway blocks, then
finds nothing left to apply.

Its `image:` line names the release tag. Replace it with the digest you
verified before applying, for the same reason the chart takes one.

### systemd (bare metal)

```bash
sudo mkdir -p /opt/sessionlayer /etc/sessionlayer
sudo cp target/controlplane-*.jar /opt/sessionlayer/controlplane.jar
sudo cp deploy/systemd/control-plane.env.example /etc/sessionlayer/control-plane.env
sudo chmod 600 /etc/sessionlayer/control-plane.env
# edit the file with real values, then:
sudo cp deploy/systemd/sessionlayer-control-plane.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sessionlayer-control-plane
```

The unit runs under `DynamicUser=yes`: systemd allocates an unprivileged UID
for the process's lifetime with no `useradd` step, since the Control Plane
needs no privileged port and keeps no local state to own across restarts.

First boot, in order: Flyway migrates the empty database, the CA provisioning
job idempotently creates the three SSH CAs plus the internal mTLS CA, and the
first-admin bootstrap arms itself. Startup is unattended; the only external
dependency is Postgres.

## Claim the first admin

An unconfigured system has empty RBAC and would deny everyone, so a one-time
bootstrap provisions the initial platform admin. Pick one of two paths:

- Config-named OIDC subject: set
  `sessionlayer.bootstrap.admin-subject=<oidc-subject>` (and
  `sessionlayer.bootstrap.admin-subject-kind=user|group`) before first boot;
  that identity is the first platform admin.
- Printed-once credential: with no subject configured, the Control Plane
  prints a bootstrap credential to its log exactly once; claiming it
  provisions the admin.

Either way the bootstrap self-disables once a platform admin exists, and its
use is audited.

The claim grants the platform-admin role to a **subject**. It does not hand you
a credential. So the subject you name has to be one you can already
authenticate as, and which one that is depends on whether you run an IdP.

### With an IdP

Your OIDC subject is the subject. Configure OIDC, claim with that subject, sign
in, and the bearer token you receive carries the admin role. Nothing else is
needed, and the rest of this section does not apply.

### Without an IdP

A subject nobody can authenticate as is a locked-out system, so arm one
narrow scheme before first boot, use it once to mint a durable machine
credential, then switch it off. Set these alongside the rest of your
configuration:

The escape hatch is a bootstrap tool, not a credential. Its whole job is to
let you claim one credential and create another.

```properties
sessionlayer.rest-security.basic-auth.enabled=true
sessionlayer.rest-security.basic-auth.username=installer
# BCrypt hash of the password, never the password itself.
sessionlayer.rest-security.basic-auth.password-hash=$2b$10$examplehashonlynotarealhash
sessionlayer.rest-security.basic-auth.allowed-cidrs=203.0.113.7/32
```

Generate the hash with any BCrypt tool, for example
`htpasswd -bnBC 10 "" '<password>' | tr -d ':\n'` from `apache2-utils`. It is
a bare BCrypt hash: Spring's `{bcrypt}` prefix is not used, and OpenSSL cannot
produce this format. If no BCrypt tool is available, the Control Plane's own
encoder ships inside its jar.

> **Warning:** HTTP Basic is not a first-class scheme. It is reachable only
> from the listed CIDRs, it must sit behind HTTPS, and the Control Plane warns
> at every startup while it is on. Scope the CIDR to the one workstation doing
> the install, and turn it off at the end of this section.

**Reach the Control Plane directly for the steps below, not through your
ingress.** The escape hatch matches `allowed-cidrs` against the address the
request actually arrives from. A request that has passed through an L7 proxy
presents its forwarded address in unresolved form, which the filter reads as
no address at all, so it is refused whatever you put in the list. Port-forward
to the pod, or use the service address inside the cluster. Put that address in
`allowed-cidrs`, not the load balancer's.

This matters more than it looks: the refusal is a plain `401`, identical to a
wrong password, on the one step where you hold no other credential. An
operator who has not read this has nothing to go on.

The same trap has a local form. If you reach the API as `localhost`, list
`::1/128` alongside `127.0.0.1/32`: the gate compares the peer address, and a
`localhost` that resolves over IPv6 is judged against a rule you did not think
you were writing. Addressing `127.0.0.1` explicitly avoids the question.

Boot, then read the printed credential from the log.

> **Warning:** the credential is printed to the Control Plane's console on
> first boot, so any log shipper attached to that output captures it, and it
> stays in your log store after you claim it. Either claim it before pointing
> a shipper at a fresh Control Plane, or treat the first-boot logs as secret
> material and purge them once the bootstrap has self-disabled. The
> config-named OIDC subject path avoids this entirely, since nothing is
> printed.

Claim it with the subject set to **the Basic username**, because that is the
identity your requests will carry. The claim itself is unauthenticated: the
printed credential is the only thing proving you may make it.

```bash
curl -s https://cp.example.com/v1/bootstrap/claim \
  -H "Content-Type: application/json" \
  -d '{ "credential": "<the printed credential>", "subject": "installer" }'
```

```json
{"status":"provisioned"}
```

> **Warning:** the log line that prints the credential suggests
> `"subject":"<your-oidc-subject>"`. That is right only if you run an IdP.
> Without one, sending an OIDC-shaped subject provisions an admin nobody can
> authenticate as, and the bootstrap self-disables behind you.

Now create a service account and issue it a credential, authenticating with
Basic:

```bash
SA_ID=$(curl -s -u installer https://cp.example.com/v1/service-accounts \
  -H "Content-Type: application/json" \
  -d '{ "name": "platform-admin-bot", "authMethod": "client_secret" }' | jq -r .id)

curl -s -u installer https://cp.example.com/v1/service-accounts/$SA_ID/credentials \
  -H "Content-Type: application/json" \
  -d '{ "credentialType": "client_secret" }'
```

The secret comes back exactly once. For a long-lived integration prefer
`private_key_jwt` or `mtls`, which keep no shared secret at rest, and
[Authentication](../admin-guides/authentication.md) shows both. This one step
is a shell prompt on install day, where signing a JWT to obtain your first
token is circular, so `client_secret` is the practical choice here even though
it is the weaker one in steady state.

Bind the account to the `platform-admin` role the bootstrap created:

```bash
ROLE_ID=$(curl -s -u installer "https://cp.example.com/v1/roles?limit=200" \
  | jq -r '.items[] | select(.name=="platform-admin") | .id')

curl -s -u installer https://cp.example.com/v1/role-bindings \
  -H "Content-Type: application/json" \
  -d '{ "roleId": "'"$ROLE_ID"'", "subjectKind": "user", "subject": "platform-admin-bot" }'
```

`subjectKind` is `user` and `subject` is the service account's **name**, not
its id. That looks wrong and is not: platform RBAC understands `user` and
`group` only, and a machine token's identity is the account name, so `user` is
the kind that matches it.

Exchange the credential for a bearer token, using the account's name as
`client_id`:

```bash
TOKEN=$(curl -s https://cp.example.com/v1/oauth2/token \
  -H "Content-Type: application/json" \
  -d '{ "grant_type": "client_credentials", "client_id": "platform-admin-bot",
        "client_secret": "<the secret returned once>" }' | jq -r .access_token)
```

That `$TOKEN` is what every other guide expects.

Finally, remove the four `basic-auth` properties and restart. Confirm it is
gone: the startup warning should no longer appear, a Basic request should be
refused, and the bearer token should still work.

## Distribute the session CA trust line

Nodes trust the platform's session CA and nothing else, so every node needs its
public key before it can accept a session. Export it once here and hand it to
your config management:

```bash
curl -s https://cp.example.com/v1/cas/session/public-key \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r .opensshPublicKey > sessionlayer_session_ca.pub
```

This is public verification material and safe to distribute widely. The same
endpoint serves the `host` CA, which clients need for the ProxyJump
`@cert-authority` line. [Nodes](../admin-guides/nodes.md) covers installing it
into `TrustedUserCAKeys`, and
[Certificate authorities](../admin-guides/certificate-authorities.md) covers
redistributing it before a rotation drains.

## The two network surfaces

| Listener | Default | Who connects |
|---|---|---|
| REST API + OIDC pages | `:8080` (`server.port`) | admins, users, the Dashboard, machine clients |
| mTLS gRPC plane | `:9090` built-in default, moved to `:9443` by `sessionlayer.mtls.server.port` | Gateways and Agents only |

The built-in gRPC default is `9090`, and the Gateway's `cp_mtls_endpoint` and
the Agent's `--cp-endpoint` default to `9443`, so one side has to move. This
page and the shipped Kubernetes manifest and systemd environment file all move
the Control Plane, by setting `sessionlayer.mtls.server.port=9443`. Either
port works as long as every side agrees; set it explicitly wherever you run
the process, because the container image does not set it for you. See
[Ports](../reference/ports.md) for the complete matrix.

Run the REST surface behind your TLS-terminating L7 load balancer, on HTTPS
only. `server.forward-headers-strategy=framework` is set, so the Control Plane
rebuilds each request's scheme, host and port from the proxy's `X-Forwarded-*`
headers, which is what keeps OIDC redirect URIs and issuer URLs correct behind
TLS termination. Configure the proxy to strip client-supplied forwarding
headers and insert its own.

> **Warning:** that setting does not give the Control Plane a usable client
> address. The forwarded address it parses is an unresolved one, and every
> control keyed on the client IP treats unresolved as absent: the Basic escape
> hatch refuses, and the authentication rate limiter puts everyone behind the
> proxy in one bucket. Inserting the true address in the proxy does not change
> this, which is why the per-source limit below has to live at the proxy.

Rate-limit the authentication endpoints at that proxy, **per source IP**. The
per-source part is the whole point: a limit of, say, 10 requests per minute per
address bounds what any one client can spend on `/v1/auth/verify`,
`/v1/oauth2/token` and `/v1/auth/backchannel-logout`. A single *global* cap at
the ingress is not a weaker version of this, it is worse than nothing here,
because it adds a second shared allowance that one caller can exhaust for
everyone. Size the per-source limit for your busiest legitimate client, not for
the average one.

The gRPC plane needs no external load-balancer TLS: the Control Plane mints
its own server certificate from the internal mTLS CA at runtime. Set
`sessionlayer.mtls.server.hostnames` to the DNS names Gateways and Agents will
dial, so they land in the certificate's SANs.

## Recording store

Point the Control Plane at your WORM bucket (it issues presigned PUTs;
recording bytes never pass through it):

```properties
sessionlayer.recording.worm.endpoint=https://s3.example.com
sessionlayer.recording.worm.bucket=sessionlayer-recordings
sessionlayer.recording.worm.region=us-east-1
# Blank access-key = the AWS default credential chain / IAM role.
sessionlayer.recording.worm.access-key=
sessionlayer.recording.worm.secret-key=
```

The customer recording public key, retention, and compliance-vs-governance
mode are operator settings rather than properties, managed over the API at
`/v1/operator-settings`. Configure them in
[Session recording](../admin-guides/session-recording.md).

## Before production

Work through the [production hardening checklist](../security/hardening.md).
It covers the CA key-encryption key, Postgres HA with synchronous replication
for the authz/audit tables, HTTPS origins, and the session-limit default
(unset means unlimited concurrent sessions; the Control Plane warns about this
at boot).

## Verify

```bash
curl -s http://localhost:8080/v1/healthz
curl -s http://localhost:8080/v1/version
curl -s http://localhost:8080/actuator/health/readiness
```

Expect a healthy status from the readiness check and a real version string
from `/v1/version`. Confirm the gRPC plane is listening too:

```bash
nc -zv localhost 9443
```

## Next

- [Install the Gateway](gateway.md)
- [Enroll nodes](../admin-guides/nodes.md)
- [Production hardening](../security/hardening.md)
- [Control Plane configuration reference](../reference/config-control-plane.md)
