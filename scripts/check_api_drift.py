#!/usr/bin/env python3
"""Both-direction drift check: docs/reference/api*.md vs the OpenAPI contract.

Usage: check_api_drift.py <controlplane-api-checkout>
"""
import glob
import re
import sys


def spec_operations(spec_path):
    # Purpose-built extractor for the two indentation levels under `paths:`
    # (2-space path keys, 4-space verb keys) — not a generic YAML parser; the
    # contract file is machine-checked upstream so the shape is stable.
    ops = set()
    in_paths = False
    path = None
    with open(spec_path, encoding="utf-8") as f:
        for line in f:
            if line.rstrip("\n") == "paths:":
                in_paths = True
                continue
            if in_paths and re.match(r"^[A-Za-z]", line):
                break
            if not in_paths:
                continue
            m = re.match(r"^  (/[^\s:]+):\s*$", line)
            if m:
                path = m.group(1)
                continue
            m = re.match(r"^    (get|put|post|delete|patch|head|options):\s*$", line)
            if m and path:
                ops.add((m.group(1).upper(), path))
    return ops


def documented_operations(doc_glob):
    # Documented operations always appear as a single backticked `METHOD /path`.
    ops = set()
    files = sorted(glob.glob(doc_glob))
    for name in files:
        with open(name, encoding="utf-8") as f:
            for m in re.finditer(r"`(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS) (/v1/[^`\s]*)`", f.read()):
                ops.add((m.group(1), m.group(2)))
    return files, ops


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    spec_path = sys.argv[1].rstrip("/") + "/contracts/openapi/openapi.yaml"
    spec = spec_operations(spec_path)
    files, docs = documented_operations("docs/reference/api*.md")
    _, sub = documented_operations("docs/reference/api/*.md")
    docs |= sub

    # An empty side means the extractor (or the tree) broke — never a clean pass.
    if not spec:
        print(f"FAIL: no operations extracted from {spec_path}", file=sys.stderr)
        return 1
    if not docs:
        print("FAIL: no `METHOD /v1/...` operations found in docs/reference/api*.md", file=sys.stderr)
        return 1

    undocumented = sorted(spec - docs)
    nonexistent = sorted(docs - spec)
    for verb, path in undocumented:
        print(f"UNDOCUMENTED (in spec, not in docs): {verb} {path}")
    for verb, path in nonexistent:
        print(f"NONEXISTENT (in docs, not in spec): {verb} {path}")
    if undocumented or nonexistent:
        print(f"FAIL: {len(undocumented)} undocumented, {len(nonexistent)} nonexistent "
              f"(spec {len(spec)} ops, docs {len(docs)} ops)")
        return 1
    print(f"OK: {len(spec)} operations match both ways ({', '.join(files)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
