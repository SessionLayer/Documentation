# F-docs-tone-7: agent.md pipes GET /v1/nodes through `.nodes[]` while api.md documents the `items` page envelope
- Severity: medium
- Area: tone
- Status: Verified-Fixed

reference/api.md:38–49 states that collection endpoints are cursor-paginated with the envelope `{"items": [], "nextCursor": …}`, and every other worked example in the suite honors it (quickstart.md:187 `jq -r '.items | …'`, file-transfer.md:70, requesting-access.md:130, audit examples).

installation/agent.md:124 alone does:

```bash
curl -s -H "Authorization: Bearer $TOKEN" https://cp.example.com/v1/nodes | jq '.nodes[] | {name, status, health}'
```

Either the command is broken as written (a `.nodes` key that doesn't exist) or `GET /v1/nodes` genuinely deviates from the documented envelope — both are defects; T5b-accuracy should confirm which. Assuming the envelope is `items` (as every other page implies), the rewording is:

```bash
curl -s -H "Authorization: Bearer $TOKEN" https://cp.example.com/v1/nodes | jq '.items[] | {name, status, health}'
```

**Fix (lead closure):** api.md conventions now document both envelopes (Page items vs List resource-named); agent.md confirmed correct (fc51ee7).
