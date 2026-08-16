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
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
