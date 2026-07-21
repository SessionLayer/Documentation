# File transfer

SFTP and SCP work through SessionLayer exactly as they do against a plain SSH
server — same commands, same flags — provided your grant includes the `sftp` or
`scp` capability. Every transfer is audited by protocol decoding: operation,
path, direction, size, and a SHA-256 of the content. For SFTP-protocol
transfers — which includes modern `scp` — the content itself is never captured
(one legacy-`scp` edge is called out below). This page shows both, live, on
the quickstart stack.

## Prerequisites

- [ ] The [quickstart](../getting-started/quickstart.md) stack is running and
      you completed it in your current shell.
- [ ] `curl` and `jq` on your machine.

> **Note:** the `accept-new` in these evaluation blocks is fine against the
> throwaway loopback stack; production clients pre-provision the Gateway's
> host key instead — see [SSH access](ssh-access.md).

## Transfers are a capability

Data-plane grants name the SSH capabilities they allow, and the default is
`shell` + `exec` only — file transfer is something an admin grants
deliberately. The quickstart's rule grants `sftp` and `scp`, so the commands
below work as-is. If your grant withholds them, the transfer channel is
refused with the same generic `access denied by policy` (the client then
prints `Connection closed`), while the specific reason — capability withheld —
lands in the decision log for your admin.

## SFTP

Upload a file with stock `sftp` (the quickstart's client container plays your
workstation; the `deploy%web-01` username addresses node `web-01`, as explained
in [SSH access](ssh-access.md)):

```bash
docker compose exec -T client sh -c 'echo "quarterly numbers" > /tmp/report.txt'
printf 'put /tmp/report.txt /home/deploy/report.txt\n' | \
  docker compose exec -T client sftp -b - -P 2222 -o StrictHostKeyChecking=accept-new \
  deploy%web-01@gateway
```

Downloads are the same in the other direction:

```bash
printf 'get /home/deploy/report.txt /tmp/report-copy.txt\n' | \
  docker compose exec -T client sftp -b - -P 2222 -o StrictHostKeyChecking=accept-new \
  deploy%web-01@gateway
```

## SCP

Both SCP modes work: modern `scp` (OpenSSH 9.0+) rides the SFTP protocol, and
legacy `scp -O` uses the classic exec mode — SessionLayer decodes and audits
both:

```bash
docker compose exec -T client scp -P 2222 -o StrictHostKeyChecking=accept-new \
  /tmp/report.txt deploy%web-01@gateway:/home/deploy/scp-copy.txt
```

> **Warning:** legacy `scp -O` runs over an `exec` channel, and every exec
> channel is terminal-captured — so a legacy-mode transfer's raw bytes **do
> land inside the sealed session recording** (readable only by the customer
> recording key holder, and retained for the full retention period). Modern
> `scp` and `sftp` are content-free in the recording. If the file is
> sensitive, don't use `-O` — see
> [Session recording](../admin-guides/session-recording.md).

## What the audit captures

When a transfer session ends, the Gateway reports the decoded operations into
the platform's audit stream, correlated to the session: one entry per
transferred file — `sftp.write` for an upload, `sftp.read` for a download —
plus entries for the namespace operations it saw (`rename`, `remove`,
`mkdir`, …). Look at the most recent transfer's trail (the SCP copy; every
transfer's entries have the same shape):

```bash
TOKEN=$(curl -s http://127.0.0.1:8080/v1/oauth2/token -H 'Content-Type: application/json' \
  -d '{"grant_type":"client_credentials","client_id":"quickstart-admin","client_secret":"quickstart-admin-dev-secret"}' | jq -r .access_token)
SESSION=$(curl -s "http://127.0.0.1:8080/v1/sessions" -H "Authorization: Bearer $TOKEN" \
  | jq -r '.items | sort_by(.startedAt) | last | .id')
until curl -s "http://127.0.0.1:8080/v1/audit-events?correlationId=$SESSION" -H "Authorization: Bearer $TOKEN" \
  | jq -e '[.items[] | select(.action | startswith("sftp."))] | length > 0' >/dev/null; do sleep 2; done
curl -s "http://127.0.0.1:8080/v1/audit-events?correlationId=$SESSION" -H "Authorization: Bearer $TOKEN" | \
  jq '.items[] | select(.action | startswith("sftp.")) | {action, detail}'
```

The entry carries the path (`/home/deploy/scp-copy.txt`), the direction
(`upload`), the byte count, and the streaming SHA-256 of what crossed the
wire. The copy is byte-for-byte the file you sent, so verify the hash yourself:

```bash
docker compose exec -T client sha256sum /tmp/report.txt
```

It matches the audited `sha256:` value — evidence of *exactly which bytes*
were transferred, without the platform storing the bytes.

## What is deliberately not captured

- **File content.** The audit is metadata: names, sizes, hashes, direction.
  For SFTP — including modern `scp`, which rides the SFTP subsystem — the
  transferred bytes are hashed in a streaming pass and discarded: they appear
  in no recording and no audit row. The one exception is legacy `scp -O` (the
  Warning above): its bytes ride an exec channel and are part of the terminal
  capture — the [trust model](../security/trust-model.md) states the same
  edge.
- **A hidden copy of your session.** The session recording for an SFTP
  transfer channel contains transfer *markers*, not data. Interactive shells
  are recorded in full (output and keystrokes) — file transfers are not
  shells.

> **Note:** the SHA-256 lets an auditor prove a specific file crossed the
> boundary (hash it and compare) without the platform ever holding the file.
> If your compliance regime requires content capture, SessionLayer does not
> provide it — that is a stated design boundary, not a toggle.

## Next

- [SSH access](ssh-access.md) — addressing, client config, and prompts.
- [Requesting access](requesting-access.md) — when you need a grant you don't have.
- [Session recording](../admin-guides/session-recording.md) — how recordings are sealed and replayed.
- [Audit](../admin-guides/audit.md) — searching the audit stream.
