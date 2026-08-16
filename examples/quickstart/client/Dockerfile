FROM debian:13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openssh-client \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# `docker compose exec` runs with the daemon's umask, which is 0000 here, so a
# shell redirection into a fresh file lands world-writable and `ssh` refuses to
# read its own config. Ship the two paths whose modes OpenSSH enforces, already
# correct: an append or a truncating redirect keeps the mode of a file that
# exists.
RUN install -d -m 0700 /root/.ssh \
 && install -m 0600 /dev/null /root/.ssh/config

ENTRYPOINT ["sleep", "infinity"]
