#!/bin/sh
set -eu

# The session CA exists only after the Control Plane's cold start, so it cannot
# be baked in or passed as static env: the seed writes it to the shared state
# volume and this entrypoint installs it into TrustedUserCAKeys.
if [ -f /state/session_ca.pub ]; then
	cp /state/session_ca.pub /etc/ssh/trusted_user_ca.pub
	chmod 644 /etc/ssh/trusted_user_ca.pub
fi

# Generate any missing host keys (idempotent across restarts).
ssh-keygen -A >/dev/null 2>&1 || true

mkdir -p /run/sshd
/usr/sbin/sshd -t -f /etc/ssh/sshd_config
exec /usr/sbin/sshd -D -e "$@"
