# Install the Dashboard

No server-side process runs behind the Dashboard: it is a static bundle,
built once and served by whatever serves static files in your
infrastructure, that holds no secrets and keeps its bearer token in memory
only. Building it here gets admins logging in with OIDC (auth-code + PKCE),
driving the Control Plane's REST API, and replaying recordings decrypted in
the browser, where the recording key never leaves it.

It talks to exactly three origins: the Control Plane API, your OIDC
identity provider, and the object store that serves signed recording URLs.

Prerequisites:

- [ ] Node 22 to build (see `.nvmrc` in the repo)
- [ ] a running [Control Plane](control-plane.md) on HTTPS
- [ ] an OIDC client registered for the Dashboard at your IdP
- [ ] something to serve static files that can set response headers

## Build

```bash
git clone https://github.com/SessionLayer/Dashboard.git
cd Dashboard
npm ci
VITE_CP_BASE_URL=https://cp.example.com \
VITE_OIDC_ISSUER=https://idp.example.com \
VITE_OIDC_CLIENT_ID=sessionlayer-dashboard \
npm run build
ls dist/
```

The endpoints are baked in at build time. `VITE_OIDC_AUTHORIZE_ENDPOINT`,
`VITE_OIDC_TOKEN_ENDPOINT`, `VITE_OIDC_REDIRECT_URI`, and `VITE_OIDC_SCOPE`
override the conventional defaults derived from the issuer when your IdP needs
them.

> **Note:** the build fails if any credential-bearing endpoint
> (`VITE_CP_BASE_URL`, the `VITE_OIDC_*` endpoints) is a non-localhost `http://`
> URL. HTTPS in production is enforced at build time, not discovered in an
> incident. Localhost values stay allowed so local development works.

## Serve it: the headers are part of the deployment

A client-only bundle cannot set its own security headers, so whatever fronts
`dist/` must. The repo ships three equivalent references under `deploy/`: the
header set is the contract, any server that emits it is fine.

| Asset | Use it when |
|---|---|
| `deploy/nginx.conf` + `deploy/security-headers.conf` | you run your own TLS-terminating reverse proxy; replace the three `__CP_ORIGIN__` / `__OIDC_ORIGIN__` / `__OBJECT_STORE_ORIGIN__` placeholders in `security-headers.conf` yourself |
| `deploy/Dockerfile` | you want a container: builds `dist/`, serves via nginx, and fills those same placeholders from `SL_CSP_CONNECT_SRC` automatically at container start |
| `deploy/_headers` | a static host (Netlify / Cloudflare Pages): the header set uses `REPLACE-*` tokens that your deploy pipeline must substitute before publishing, since these hosts cannot template from an environment at request time |

The set includes a strict CSP (`script-src 'self'`, no inline anything), HSTS
with preload, `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy:
no-referrer`, `Cross-Origin-Opener-Policy: same-origin`, and a locked-down
`Permissions-Policy`. `Cross-Origin-Embedder-Policy` is deliberately not set:
`require-corp` would block the cross-origin fetch that recording replay
depends on. If the UI, the Control Plane, and the object store all sit behind
the same reverse proxy, `connect-src` collapses to `'self'` alone.

`style-src` stays `'self'` with no `'unsafe-inline'`. The built `index.html`
carries no inline `<style>` blocks or `style="…"` attributes; the app's only
inline styling is React's `style={{}}` prop, which writes to the CSSOM
directly and sits outside what CSP's `style-src` governs. `e2e/csp.spec.ts`
loads the authenticated app under this exact policy and asserts zero
violations.

> **Warning:** `connect-src` must list all three origins: the Control Plane,
> the OIDC token endpoint, and the object store. Omit one and the matching flow
> breaks: data loads, login, or recording replay respectively. Unset
> `SL_CSP_CONNECT_SRC` fails closed to `'self'` only. Recording replay fetches
> the still-encrypted object directly from the signed URL, never through the
> API, which is exactly why the object-store origin appears here and why no
> bearer token ever reaches the object store.

## Run the published image

```bash
docker pull ghcr.io/sessionlayer/dashboard:v0.0.2
```

`v0.0.2` is the release tag; substitute the one you are installing. There is no
`:latest`. The image is a `linux/amd64` + `linux/arm64` index, serving `dist/`
behind unprivileged nginx on port 8080 as uid 101.

Verify it before you run it:

```bash
DIGEST=$(docker buildx imagetools inspect ghcr.io/sessionlayer/dashboard:v0.0.2 \
  --format '{{json .Manifest}}' | jq -r .digest)

cosign verify "ghcr.io/sessionlayer/dashboard@$DIGEST" \
  --certificate-identity "https://github.com/SessionLayer/Dashboard/.github/workflows/release.yml@refs/tags/v0.0.2" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"

gh attestation verify "oci://ghcr.io/sessionlayer/dashboard@$DIGEST" \
  --repo SessionLayer/Dashboard
```

```bash
docker run -d -p 8443:8080 \
  -e SL_CSP_CONNECT_SRC="https://cp.example.com https://idp.example.com https://s3.example.com" \
  "ghcr.io/sessionlayer/dashboard@$DIGEST"
```

Deploy `$DIGEST`, not the tag. [Supply chain](../security/supply-chain.md)
covers reading the image's SBOM and the rest of the release evidence.

> **Warning:** the endpoints are compiled into the bundle, and the release
> build passes no `VITE_*` values, so the published image talks to
> `http://localhost:8080` and no identity provider. It is an evaluation
> artifact. Every real deployment builds its own image with its own endpoints:
>
> ```bash
> docker build -f deploy/Dockerfile \
>   --build-arg VITE_CP_BASE_URL=https://cp.example.com \
>   --build-arg VITE_OIDC_ISSUER=https://idp.example.com \
>   --build-arg VITE_OIDC_CLIENT_ID=sessionlayer-dashboard \
>   -t sessionlayer-dashboard .
> ```
>
> `SL_CSP_CONNECT_SRC` is the exception: it is applied to the served response
> headers at container start, so it stays a runtime value either way.

## Log in

Browse to the Dashboard origin and sign in through your IdP. The Dashboard is
an OIDC public client using auth-code + PKCE; tokens live in memory (a page
reload logs you out, deliberately). What you can see and do is governed by
[platform RBAC](../admin-guides/rbac.md): a fresh identity with no role
bindings sees denials, which is default-deny working.

## Verify

```bash
curl -sI https://dashboard.example.com/ | grep -i -e content-security-policy -e strict-transport-security
# expect:
# content-security-policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://cp.example.com https://idp.example.com https://s3.example.com; frame-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'; object-src 'none'; worker-src 'none'; upgrade-insecure-requests
# strict-transport-security: max-age=63072000; includeSubDomains; preload
```

A missing or empty `connect-src` means the serving layer in front of `dist/`
is not applying `security-headers.conf` (or its equivalent); check the
include before troubleshooting further.

## Next

- [RBAC](../admin-guides/rbac.md)
- [Session recording](../admin-guides/session-recording.md)
- [Authentication](../admin-guides/authentication.md)
- [Production hardening](../security/hardening.md)
