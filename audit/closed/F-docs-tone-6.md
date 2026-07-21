# F-docs-tone-6: Variables used in runnable blocks with no on-page source; two procedural pages have no prerequisites block at all
- Severity: medium
- Area: tone
- Status: Verified-Fixed

STYLE.md: no placeholder without the immediately-preceding line saying exactly how to get the value; prerequisites at the top of every procedural page. The admin guides mostly nail this with a standard prereq bullet ("The examples use a bearer token in `$TOKEN` — see [Authentication](…)"). These pages don't:

1. **installation/gateway.md:82, 100 — `$CP_DSN`** is never defined anywhere on the page (or the suite). The prereq at :18 says "access to the Control Plane's Postgres" but never names the variable. Add before the first psql block: "`$CP_DSN` is a Postgres connection string for the Control Plane's database, as the owner role (for example `postgres://sessionlayer:…@db.example.com:5432/sessionlayer`)."
2. **installation/agent.md:124 — `$TOKEN`** appears only in the final verify step; nothing on the page mints or explains it. Add the standard sentence: "`$TOKEN` is an admin bearer token — see [Authentication](../admin-guides/authentication.md)."
3. **security/hardening.md:72, 125 — `$CP_DATABASE_URL`**, and `$TOKEN` in step 3 (:93) — neither is explained on this page (session-recording.md explains `$CP_DATABASE_URL`; hardening must too, it's the go-live page people execute top to bottom). One line under "The quick self-audit" or at first use suffices.
4. **admin-guides/certificate-authorities.md** — a procedural page (four curl commands using `$TOKEN`) with **no Prerequisites block at all**. Add the section other admin guides use:
   > ## Prerequisites
   > - The `ca:manage` platform permission (`ca:rotate` for rotation); a bearer token in `$TOKEN` ([Authentication](authentication.md)).
5. **admin-guides/session-recording.md** — prerequisites exist only as an H3 nested under "Provision the customer recording key" (:41), so the export command at :122 uses `$TOKEN` with no source. Either promote a page-top prerequisites block (Postgres access, `$TOKEN`, offline key store) or add the `$TOKEN` sentence at :120.
6. **operations/troubleshooting.md:43 — `$TOKEN`** unexplained (low-priority: runbook audience, but the one-line fix is cheap).

Also (low): installation/control-plane.md:41–47 uses `<owner-password>`/`<runtime-password>` where the preceding prose says *what* to set but not how to obtain/generate it — mirror hardening.md:63–64's approach (`use-a-generated-secret-here` literal) or add "generate one: `openssl rand -base64 24`" alongside the alphanumeric constraint.

**Fix (lead closure):** every flagged variable now has an on-page source; certificate-authorities.md gained a Prerequisites block; session-recording export + troubleshooting + hardening annotated; control-plane.md password generation hint added (lead + 5a225c2).
