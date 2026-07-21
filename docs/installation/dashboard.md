# Install the Dashboard

When you finish this page the admin web UI is built and served: admins log in
with OIDC (auth-code + PKCE), drive the Control Plane's REST API, and replay
recordings decrypted **in the browser** — the recording key never leaves it.

The Dashboard is a static bundle. It holds no secrets, keeps its bearer token
in memory only, and talks to exactly three origins: the Control Plane API, your
OIDC identity provider, and the object store that serves signed recording URLs.

Prerequisites:

- [ ] Node 22 to build (see `.nvmrc` in the repo)
- [ ] a running [Control Plane](control-plane.md) on HTTPS
- [ ] an OIDC client registered for the Dashboard at your IdP
- [ ] something to serve static files that can set response headers

## Build

```bash
git clone https://github.com/SessionLayer/ControlPlane-Dashboard.git
cd ControlPlane-Dashboard
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

> **Note:** the build **fails** if any credential-bearing endpoint
> (`VITE_CP_BASE_URL`, the `VITE_OIDC_*` endpoints) is a non-localhost `http://`
> URL. HTTPS in production is enforced at build time, not discovered in an
> incident. Localhost values stay allowed so local development works.

## Serve it — the headers are part of the deployment

A client-only bundle cannot set its own security headers, so whatever fronts
`dist/` must. The repo ships three equivalent references under `deploy/` — the
header *set* is the contract, any server that emits it is fine:

| Asset | Use it when |
|---|---|
| `deploy/nginx.conf` + `deploy/security-headers.conf` | you run your own TLS-terminating reverse proxy |
| `deploy/Dockerfile` | you want a container: builds `dist/`, serves via nginx, fills the CSP allow-list from `SL_CSP_CONNECT_SRC` at start |
| `deploy/_headers` | a static host (Netlify / Cloudflare Pages) |

The set includes a strict CSP (`script-src 'self'`, no inline anything), HSTS
with preload, `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy:
no-referrer`, and a locked-down `Permissions-Policy`.

Container example:

```bash
docker build -f deploy/Dockerfile -t sessionlayer-dashboard .
docker run -d -p 8443:8080 \
  -e SL_CSP_CONNECT_SRC="https://cp.example.com https://idp.example.com https://s3.example.com" \
  sessionlayer-dashboard
```

> **Warning:** `connect-src` must list all three origins — the Control Plane,
> the OIDC token endpoint, and the object store. Omit one and the matching flow
> breaks: data loads, login, or recording replay respectively. Unset
> `SL_CSP_CONNECT_SRC` fails closed to `'self'` only. Recording replay fetches
> the still-encrypted object **directly** from the signed URL — never through
> the API — which is exactly why the object-store origin appears here and why
> no bearer token ever reaches the object store.

## Log in

Browse to the Dashboard origin and sign in through your IdP. The Dashboard is
an OIDC public client using auth-code + PKCE; tokens live in memory (a page
reload logs you out — deliberate). What you can see and do is governed by
[platform RBAC](../admin-guides/rbac.md) — a fresh identity with no role
bindings sees denials, which is default-deny working.

## Next

- [RBAC](../admin-guides/rbac.md)
- [Session recording](../admin-guides/session-recording.md)
- [Authentication](../admin-guides/authentication.md)
- [Production hardening](../security/hardening.md)
