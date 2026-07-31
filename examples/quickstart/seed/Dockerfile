FROM debian:13-slim

# psql for the seed statements, ssh-keygen to convert the session CA public key
# into an OpenSSH TrustedUserCAKeys line, openssl for the demo customer key.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      postgresql-client \
      openssh-client \
      openssl \
 && rm -rf /var/lib/apt/lists/*

COPY seed.sh /usr/local/bin/seed.sh
RUN chmod +x /usr/local/bin/seed.sh
ENTRYPOINT ["/usr/local/bin/seed.sh"]
