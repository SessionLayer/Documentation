# syntax=docker/dockerfile:1
# SessionLayer Gateway — installed from the signed, verified GitHub Release,
# not built from source. Mirrors cp.Dockerfile's install-a-verified-release
# pattern (docs/security/supply-chain.md): download the release binary + its
# keyless cosign Sigstore bundle, verify against the exact expected
# release-workflow identity, and only then run it. A verification failure
# fails the image build.
FROM alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d AS fetch
ARG GW_TAG=0.0.1
ARG GW_REPO=SessionLayer/Gateway
ARG COSIGN_VERSION=v3.1.2
# cosign's own checksum (not just TLS-to-github.com) roots the whole
# verify-then-use chain — an unverified cosign binary is a verifier that
# would approve anything.
ARG COSIGN_SHA256=f7622ed3cf22e55e1ae6377c080979ff77a22da9981c11df222a2e444991e7cf
RUN apk add --no-cache curl
RUN curl -fsSL "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-amd64" -o /usr/local/bin/cosign \
 && echo "${COSIGN_SHA256}  /usr/local/bin/cosign" | sha256sum -c - \
 && chmod +x /usr/local/bin/cosign
WORKDIR /dl
RUN curl -fsSLO "https://github.com/${GW_REPO}/releases/download/v${GW_TAG}/gateway" \
 && curl -fsSLO "https://github.com/${GW_REPO}/releases/download/v${GW_TAG}/gateway.cosign.sigstore.json" \
 && cosign verify-blob gateway \
      --bundle gateway.cosign.sigstore.json \
      --certificate-identity "https://github.com/${GW_REPO}/.github/workflows/release.yml@refs/tags/v${GW_TAG}" \
      --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
 && chmod +x gateway

# debian-slim, not distroless: the compose healthcheck / operator shell needs
# a shell+coreutils; this is a throwaway evaluation container, not the
# product's own hardened deploy/Dockerfile (unaffected by this change).
FROM debian:trixie-slim@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=fetch /dl/gateway /usr/local/bin/gateway
ENTRYPOINT ["/usr/local/bin/gateway"]
