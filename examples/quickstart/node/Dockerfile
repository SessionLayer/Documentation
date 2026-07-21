# The quickstart node: a real OpenSSH server on slim Debian 13, adapted from the
# platform's canonical test node (testing/docker/sshd in the source tree).
#
# Cert auth model (Design §3): this sshd trusts ONLY the SessionLayer session CA
# via TrustedUserCAKeys. The entrypoint installs the CA public key from the
# seed-written state volume. Login accounts `deploy` and `dba` are the
# RBAC-resolved Linux principals.
FROM debian:13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openssh-server \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /run/sshd \
 # -p '*' => no password login, but the account is NOT locked ('!'), so OpenSSH
 # (UsePAM no) still permits certificate auth. A locked '!' account is refused
 # with "account is locked" even for valid certs.
 && useradd --create-home --shell /bin/bash -p '*' deploy \
 && useradd --create-home --shell /bin/bash -p '*' dba \
 && passwd --lock root \
 && touch /etc/ssh/trusted_user_ca.pub \
 && chmod 644 /etc/ssh/trusted_user_ca.pub

COPY sshd_config /etc/ssh/sshd_config
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 22
# sshd -D -e stays foreground and logs to stderr; VERBOSE logging surfaces the
# cert key-id (session id + identity) — the node-local audit trail.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
