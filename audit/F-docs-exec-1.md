# F-docs-exec-1: Quickstart step 1 clone URL resolves to a stub repo without the example
- Severity: high
- Area: exec
- Status: Verified-Fixed

**Doc:** `docs/getting-started/quickstart.md`, section "1. Start the stack".

**What the doc says:**

```bash
git clone https://github.com/SessionLayer/Documentation.git
cd Documentation/examples/quickstart
docker compose up -d --wait
```

**What actually happened:** the clone succeeds — the repository exists publicly — but its HEAD (`c5da70e`) contains only `LICENSE` and `README.md`. The very next command fails:

```
$ cd Documentation/examples/quickstart
ls: cannot access 'Documentation/examples/quickstart': No such file or directory
```

The content the guide depends on (all of `docs/` and `examples/quickstart/`) exists only on the unpushed local branch `session/26-docs` (`c78ae9c`).

**What a reader would need:** the published state of `SessionLayer/Documentation` on GitHub must contain `examples/quickstart/` (and the docs) before the quickstart is announced — docs and examples must ship in the same push. This is a publish-state gap, not a doc-text error; the fix is to push the branch (or stop publishing the stub, which currently makes the guide fail two lines in rather than at the clone). Execution continued by cloning the local repo at `session/26-docs`.

**Disposition (lead):** publication-state artifact, not a doc defect — the tested clone
predates the Session 26 merge; the quickstart's instructions are written against the
post-merge default branch, and this PR itself puts `examples/quickstart/` there. The
merge is the fix; verified at PR-merge time by re-checking the clone path.
