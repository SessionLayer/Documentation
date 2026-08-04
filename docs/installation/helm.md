# Deploy with Helm

Each component ships its own chart, inside its own repository, under
`deploy/helm/`. There is no umbrella chart: the four components version and
roll independently, and one release object spanning all of them would couple
every upgrade to every other.

| Component | Chart | Repository |
|---|---|---|
| Control Plane | `deploy/helm/sessionlayer-controlplane` | [SessionLayer/ControlPlane](https://github.com/SessionLayer/ControlPlane) |
| Gateway | `deploy/helm/sessionlayer-gateway` | [SessionLayer/Gateway](https://github.com/SessionLayer/Gateway) |
| Agent | `deploy/helm/sessionlayer-agent` | [SessionLayer/Agent](https://github.com/SessionLayer/Agent) |
| Dashboard | `deploy/helm/sessionlayer-dashboard` | [SessionLayer/Dashboard](https://github.com/SessionLayer/Dashboard) |

No chart repository is published. Install from a checkout of the component's
repository at the tag you are deploying, or run `helm package` on it and host
the tarball wherever your cluster's tooling reads charts from.

> **Warning:** these charts are validated statically only. No chart has been
> installed into a live cluster as part of this project's testing, so a first
> install is yours to validate. The plain manifests under each repository's
> `deploy/kubernetes/` have the same status and remain the reference for a
> deployment that does not use Helm.

## Nothing installs with a working credential

No chart defaults a credential to a working value. A missing one fails at
render time with a message naming the value and the keys it expects, so the
failure lands in your terminal, not in a `CrashLoopBackOff` an hour later:

```console
$ helm template cp deploy/helm/sessionlayer-controlplane
Error: execution error at (sessionlayer-controlplane/templates/deployment.yaml:25:28): sessionlayer-controlplane: set recording.worm.endpoint to your WORM object store's URL. The application's built-in default points at a development MinIO with a well-known credential.
```

Set that, and the next one names itself the same way:

```console
$ helm template cp deploy/helm/sessionlayer-controlplane \
    --set recording.worm.endpoint=https://worm.example.com \
    --set oidc.issuer=https://idp.example.com \
    --set oidc.clientId=sessionlayer-controlplane \
    --set oidc.redirectUri=https://cp.example.com/v1/auth/callback
Error: execution error at (sessionlayer-controlplane/templates/deployment.yaml:56:25): sessionlayer-controlplane: set secrets.existingSecret to the name of a Secret carrying SPRING_FLYWAY_PASSWORD, SPRING_FLYWAY_PLACEHOLDERS_CPRUNTIMEPASSWORD, SPRING_R2DBC_PASSWORD, SESSIONLAYER_CA_LOCAL_KEK_BASE64, SESSIONLAYER_OIDC_CLIENT_SECRET, SESSIONLAYER_OIDC_STATE_HMAC_KEY, SESSIONLAYER_RECORDING_WORM_ACCESS_KEY and SESSIONLAYER_RECORDING_WORM_SECRET_KEY. This chart never creates one.
```

The pattern is deliberate on a platform whose components refuse to start on a
development credential anyway. The Control Plane will not boot without a real
CA key-encryption key; a chart that supplied one so the install "worked" would
have papered over the control, and every pod would carry certificate authority
private keys wrapped under a public constant.

In the Control Plane and Agent charts every credential is a reference: you name
a Secret you created, and the chart never sees the value. The Dashboard chart
takes no credential at all, since the bundle holds none. Two consequences worth
planning for:

- Rotating one is a Secret update plus a pod restart, not a `helm upgrade`.
- Helm stores the values a release was installed with, inside the cluster.
  Where the credential is a reference, `helm get values` returns a name rather
  than secret material.

### The Gateway's exception

The Gateway reads one JSON file, and that file carries its enrollment token.
There is no per-field environment override, since `SL_GATEWAY_CONFIG` names the
file's path rather than its contents, so the token has to live inside
`gateway.json`. The chart offers the only two shapes that can be right:

- `config.existingSecret` names a Secret whose `gateway.json` key holds the
  complete file. This is the production path: the chart renders no
  configuration of its own, and the token never reaches a values file.
- Left unset, the chart renders `gateway.json` into a Secret it creates, from
  `bootstrap.enrollmentToken` and the values around it. A token passed that way
  does reach Helm's release storage, and stays in the release history.

The token is single-use and short-TTL, so what release storage retains after
enrollment is a spent credential rather than a standing one. That bounds the
exposure. It does not remove it, which is why the first path is the one to
deploy with.

Both are stricter than the manifest the chart translates:
`deploy/kubernetes/gateway.yaml` carries the same file in a ConfigMap.

## Pin the image by digest

Every chart takes `image.repository`, `image.tag` and `image.digest`. An empty
tag resolves to the chart's `appVersion`, which is the component release the
chart was published for. A digest wins over a tag whenever both are set:

```bash
DIGEST=$(docker buildx imagetools inspect ghcr.io/sessionlayer/controlplane:v0.0.2 \
  --format '{{json .Manifest}}' | jq -r .digest)

helm upgrade --install cp deploy/helm/sessionlayer-controlplane \
  --namespace sessionlayer --create-namespace \
  --set image.digest="$DIGEST" \
  --set secrets.existingSecret=sessionlayer-controlplane-secrets \
  --set recording.worm.endpoint=https://worm.example.com \
  --set oidc.issuer=https://idp.example.com \
  --set oidc.clientId=sessionlayer-controlplane \
  --set oidc.redirectUri=https://cp.example.com/v1/auth/callback
```

Verify the digest before you pin it. [Supply chain](../security/supply-chain.md)
covers `cosign verify`, `gh attestation verify` and reading the image's SBOM,
and explains why a registry tag is not the thing to deploy.

## Install order

The order is the platform's trust order, not a Helm constraint:

1. Control Plane. It provisions the certificate authorities and the internal
   mTLS CA on first boot, and nothing else can enroll until it is ready.
2. Gateway. Enrolling needs a running Control Plane, the mTLS trust anchor,
   and a single-use enrollment token you mint over the API.
3. Agent. Its chart refuses to render without at least one Gateway endpoint
   and the name that Gateway enrolled under, so the Gateway comes first.
4. Dashboard, at any point after the Control Plane. Nothing depends on it and
   it depends on nothing but the API.

Each component's installation page covers its own chart's values and the
out-of-band steps around it:
[Control Plane](control-plane.md), [Gateway](gateway.md), [Agent](agent.md),
[Dashboard](dashboard.md).

## Network policy is on by default

All four charts render a NetworkPolicy, enabled, permitting only the peers the
component genuinely talks to. The CIDR lists for peers outside the cluster
start empty: an empty list denies that traffic, which is visible immediately,
where a placeholder range would permit egress to hosts that are not your object
store, your identity provider or your fleet. Fill in the ranges your deployment
needs and no more.

The Dashboard is the exception on its ingress side. Its rule restricts the
port to 8080 and names no source at all, which permits every source a
NetworkPolicy can express. An ingress controller lives in a namespace the chart
cannot guess, so narrowing it with `networkPolicy.ingressFromPodSelector` and
`networkPolicy.ingressFromNamespaceSelector` is left to you.

All of this assumes a CNI that enforces NetworkPolicy. On one that does not,
the objects are accepted by the API server and enforce nothing, which looks
identical to a working policy from `kubectl`.

## Verify a render before you apply it

```bash
helm lint deploy/helm/sessionlayer-controlplane \
  -f deploy/helm/sessionlayer-controlplane/ci/production-values.yaml

helm template cp deploy/helm/sessionlayer-controlplane \
  -f deploy/helm/sessionlayer-controlplane/ci/production-values.yaml \
  | kubeconform -strict -summary
```

```console
==> Linting deploy/helm/sessionlayer-controlplane
[INFO] Chart.yaml: icon is recommended

1 chart(s) linted, 0 chart(s) failed
Summary: 6 resources found parsing stdin - Valid: 6, Invalid: 0, Errors: 0, Skipped: 0
```

> **Warning:** `helm lint` exits 0 when a required value is missing. It reports
> each one as `[INFO]` and still prints `0 chart(s) failed`:
>
> ```console
> $ helm lint deploy/helm/sessionlayer-controlplane
> engine.go:214: [INFO] Missing required value: sessionlayer-controlplane: set secrets.existingSecret to the name of a Secret carrying SPRING_FLYWAY_PASSWORD, ...
> engine.go:214: [INFO] Missing required value: sessionlayer-controlplane: set recording.worm.endpoint to your WORM object store's URL. ...
> ==> Linting deploy/helm/sessionlayer-controlplane
> [INFO] Chart.yaml: icon is recommended
>
> 1 chart(s) linted, 0 chart(s) failed
> $ echo $?
> 0
> ```
>
> A clean lint tells you the chart's structure and schema are sound and tells
> you nothing about whether it would refuse an unsafe install. `helm template`
> is the command that fails on a missing credential, which is why both are run
> above and why neither substitutes for the other.

Each chart's `ci/` directory holds the values file it is linted and
schema-checked against, with every optional path switched on. Start from it
when you want to see what a fully-configured render looks like.

Those two commands are the ones CI runs. Every repository's `ci.yml` carries a
`chart` job, on every push and every pull request, alongside the build gate and
the image job. It lints each chart, renders every values file in `ci/`, and
schema-checks the output with `kubeconform -strict`. helm, kubeconform and the
Kubernetes API version are all pinned, the last of those because the schemas are
fetched per run and an unpinned version moves what a green check means. The job
reads kubeconform's JSON summary rather than its exit code, which is `0` over an
empty file and reports a schema it could not find as skipped rather than as
failed.

The half of that job with teeth asserts the charts refuse what they must refuse.
Everything above would still pass if every `required` in a chart were deleted,
so the job also renders with each secret reference removed and demands a failure
naming it. That is the property this page describes, checked rather than
asserted.

## See also

- [Supply chain](../security/supply-chain.md): verifying an image before you pin its digest
- [Production hardening](../security/hardening.md): the go-live checklist the charts do not enforce for you
- [Deployment topology](../operations/deployment-topology.md): what talks to what, and on which port
