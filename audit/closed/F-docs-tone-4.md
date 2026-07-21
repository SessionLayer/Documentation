# F-docs-tone-4: Gateway install/config pages use "alice" as the Linux-login half of SSH addressing — everywhere else the login is "deploy"
- Severity: medium
- Area: tone
- Status: Verified-Fixed

STYLE.md fixes the example roles: `alice@example.com` is the user identity, `deploy` is the Linux login. The teaching page (user-guide/ssh-access.md) is scrupulous about this: the username-encoding half before `%` is always `deploy` (`deploy%web-01@…`), because that half is the Linux login, not the person.

Three places break the model by putting `alice` in the login position:

- installation/gateway.md:145–147 — "wildcard DNS (`ssh alice@web-01.ssh.example.com` …), username encoding (`ssh 'alice%web-01'@gw.example.com`)"
- installation/gateway.md:160 — verify step: `ssh -p 2222 alice@gw.example.com`
- reference/config-gateway.md:87 — `ssh.node_dns_suffixes` effect column: "(`alice%web-01.ssh.example.com` → `web-01`)"

This is exactly the confusion the suite elsewhere works to prevent (ssh-access.md and quickstart.md both stress that the pin's principals are logins you may *ask for*, and rbac.md that a user "never picks an arbitrary Linux principal"). An admin copying gateway.md's forms will teach users to put their identity where `sshd` expects a login.

**Suggested rewording:**
- gateway.md:145–147: "wildcard DNS (`ssh deploy@web-01.ssh.example.com` with a `*.ssh.example.com` record pointing at the Gateway), username encoding (`ssh 'deploy%web-01'@gw.example.com`), or ProxyJump"
- gateway.md:160: `ssh -p 2222 deploy%web-01@gw.example.com` (keeps the verify step meaningful — a well-formed target that still gets the generic denial before rules exist)
- config-gateway.md:87: "(`deploy%web-01.ssh.example.com` → `web-01`)"

**Fix (lead closure):** deploy in the login position of every addressing example (81f2c6c).
