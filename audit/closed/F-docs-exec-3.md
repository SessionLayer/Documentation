# F-docs-exec-3: OTP section issues a passcode but gives no runnable way to use it on the stack
- Severity: medium
- Area: exec
- Status: Verified-Fixed

**Doc:** `docs/user-guide/ssh-access.md`, section "How authentication looks" (One-time passcode).

**What the doc says:** "Issue one now (in production an admin runs this and hands you the code)" — followed by a runnable `curl` block that mints the OTP (this works; it returned `{"otp":"XNM32AQP3P37VXVWJ6O7KJ4ZAQ","expiresAt":...}`), and then a `text` block showing the prompt:

```text
$ ssh deploy%web-01@gw.example.com
SessionLayer
Enter a one-time passcode, or press Enter to log in via your browser.
(deploy%web-01@gw.example.com) One-time passcode:
```

**What actually happened:** there is no way to reach that prompt by following the page. Two obstacles, neither mentioned:

1. The quickstart client container has Alice's pinned key, so `ssh` authenticates silently via publickey — the keyboard-interactive prompt is never offered. Reaching it requires improvising `-o PubkeyAuthentication=no` (or similar), which the page never states.
2. The illustrated command targets `gw.example.com`, not the stack's `gateway`, and the page is explicitly framed as "Every command here runs against the quickstart stack".

An improvised attempt (pubkey disabled, pty faked via `script`, OTP fed on stdin) hung because the passcode must be typed interactively at the prompt; a non-interactive reader cannot complete the flow at all, and an interactive reader still has to invent the pubkey-bypass flag.

**What a reader would need:** either (a) a runnable variant, e.g. `docker compose exec client ssh -o PubkeyAuthentication=no -p 2222 deploy%web-01@gateway`, with a note that this must be run interactively (`docker compose exec client …` without `-T`), or (b) an explicit statement that the transcript is illustrative only and cannot be reproduced while the pinned key exists (with the flag needed if you want to try). As written, the page hands the reader a live 300-second code and no door to put it in.

**Fix:** ssh-access.md OTP section now ships a runnable stack variant (-o PubkeyAuthentication=no, target gateway:2222, interactive - no -T) with a skip note for non-interactive runners; transcript explicitly framed as what the exchange looks like. Flags verified live (askpass): OTP path authenticates.
