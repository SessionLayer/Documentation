# Deploy with Helm

Each component ships its own chart, inside its own repository, under
`deploy/helm/`. There is no umbrella chart. The four components have
independent release cadences and independent blast radii, and a chart that
rolled the Control Plane every time a Gateway value changed would be the
wrong shape for both.

| Component | Chart | Repository |
|---|---|---|
| Control Plane | `deploy/helm/sessionlayer-controlplane` | [SessionLayer/ControlPlane](https://github.com/SessionLayer/ControlPlane) |
| Gateway | `deploy/helm/sessionlayer-gateway` | [SessionLayer/Gateway](https://github.com/SessionLayer/Gateway) |
| Agent | `deploy/helm/sessionlayer-agent` | [SessionLayer/Agent](https://github.com/SessionLayer/Agent) |
| Dashboard | `deploy/helm/sessionlayer-dashboard` | [SessionLayer/Dashboard](https://github.com/SessionLayer/Dashboard) |

No chart repository is published. Install from a checkout of the component's
repository at the tag you are deploying, or run `helm package` on it and host
the tarball wherever your cluster's tooling reads charts from.

> **Warning:** these charts are validated statically only: `helm lint`,
> `helm template`, each chart's `values.schema.json`, and `kubeconform
> -strict` against the Kubernetes API schemas. No chart has been installed
> into a live cluster as part of this project's testing, so a first install
> is yours to validate. The plain manifests under each repository's
> `deploy/kubernetes/` have the same status and remain the reference for a
> deployment that does not use Helm.

## Nothing installs with a working credential

No chart defaults a credential to a working value. Each one is referenced by
the name of a Secret you create out of band, and a missing reference fails at
render time with a message naming the value and the keys it expects. The
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

Two consequences worth planning for:

- Rotating a credential is a Secret update plus a pod restart, not a
  `helm upgrade`.
- Helm stores the values a release was installed with, inside the cluster.
  Because the credentials are references, `helm get values` returns names
  rather than secret material.

> **Warning:** the Gateway chart is the one exception, and a deliberate one.
> `bootstrap.enrollmentToken` can be passed as a value, which does put it in
> Helm's release storage. The token is single-use and short-TTL, so what is
> retained is a spent credential, but the way to avoid it entirely is
> `config.existingSecret`: put the whole `gateway.json` in a Secret you create,
> and the chart renders no configuration of its own.

## Pin the image by digest

Every chart takes `image.repository`, `image.tag` and `image.digest`. An empty
tag resolves to the chart's `appVersion`, which is the component release the
chart was published for. A digest wins over a tag whenever both are set:

```bash
helm upgrade --install cp deploy/helm/sessionlayer-controlplane \
  --namespace sessionlayer --create-namespace \
  --set image.digest=sha256:<the digest cosign verified> \
  --set secrets.existingSecret=sessionlayer-controlplane-secrets \
  ...
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
3. Agent and Dashboard, in either order. Both need a Control Plane; neither
   needs the other.

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

The Dashboard is the one whose ingress side is open by default, on the
container port, to the whole cluster. An ingress controller lives in a
namespace the chart cannot guess, so narrowing that is left to you once you
know your controller's labels.

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

Each chart's `ci/` directory holds the values file it is linted and
schema-checked against, with every optional path switched on. Start from it
when you want to see what a fully-configured render looks like.

## See also

- [Supply chain](../security/supply-chain.md): verifying an image before you pin its digest
- [Production hardening](../security/hardening.md): the go-live checklist the charts do not enforce for you
- [Deployment topology](../operations/deployment-topology.md): what talks to what, and on which port
