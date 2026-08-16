# syntax=docker/dockerfile:1
# CP_TAG is the git release tag (what the release workflow signed as).
# CP_JAR_VERSION is the jar's own filename version, from pom.xml's <version>.
# They are equal today, but they remain separate build args because nothing
# forces them to agree: the release workflow names the SBOM from the tag and
# the jar from the pom, so an unbumped pom would silently ship a filename
# that disagrees with the tag.
FROM alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d AS fetch
ARG CP_TAG=0.0.2
ARG CP_JAR_VERSION=0.0.2
ARG CP_REPO=SessionLayer/ControlPlane
ARG COSIGN_VERSION=v3.1.2
ARG COSIGN_SHA256=f7622ed3cf22e55e1ae6377c080979ff77a22da9981c11df222a2e444991e7cf
RUN apk add --no-cache curl
RUN curl -fsSL "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-amd64" -o /usr/local/bin/cosign \
 && echo "${COSIGN_SHA256}  /usr/local/bin/cosign" | sha256sum -c - \
 && chmod +x /usr/local/bin/cosign
WORKDIR /dl
RUN curl -fsSLO "https://github.com/${CP_REPO}/releases/download/v${CP_TAG}/controlplane-${CP_JAR_VERSION}.jar" \
 && curl -fsSLO "https://github.com/${CP_REPO}/releases/download/v${CP_TAG}/controlplane-${CP_JAR_VERSION}.jar.sigstore.json" \
 && cosign verify-blob "controlplane-${CP_JAR_VERSION}.jar" \
      --bundle "controlplane-${CP_JAR_VERSION}.jar.sigstore.json" \
      --certificate-identity "https://github.com/${CP_REPO}/.github/workflows/release.yml@refs/tags/v${CP_TAG}" \
      --certificate-oidc-issuer "https://token.actions.githubusercontent.com"

FROM eclipse-temurin:25-jre@sha256:681c543d6f36c50f45e9b5226930a46203dcfa351d3670e9d0bdf0dabae53539
ARG CP_JAR_VERSION=0.0.2
# curl is only for the compose healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*
COPY --from=fetch /dl/controlplane-${CP_JAR_VERSION}.jar /app/controlplane.jar
EXPOSE 8080 9443
ENTRYPOINT ["java", "-jar", "/app/controlplane.jar"]
