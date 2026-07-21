# syntax=docker/dockerfile:1
# SessionLayer Control Plane, built from source (the product repo ships no
# Dockerfile; the released artifact is the Spring Boot jar). The `src` build
# context is the ControlPlane-API repository (see compose.yaml).

FROM eclipse-temurin:25-jdk AS build
WORKDIR /src
COPY --from=src / .
# Tests need Docker-in-Docker (Testcontainers); the quickstart verifies the
# running stack instead, so skip them here.
RUN --mount=type=cache,target=/root/.m2 \
    ./mvnw -B -ntp -DskipTests package \
 && cp target/controlplane-*.jar /controlplane.jar

FROM eclipse-temurin:25-jre
# curl is only for the compose healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /controlplane.jar /app/controlplane.jar
EXPOSE 8080 9443
ENTRYPOINT ["java", "-jar", "/app/controlplane.jar"]
