# A stock Debian 13 OpenSSH *client*, so the quickstart never depends on (or
# touches) the SSH setup of the machine you run it on. The guide `exec`s ssh,
# sftp, and scp in here; the container just stays alive.
FROM debian:13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openssh-client \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["sleep", "infinity"]
