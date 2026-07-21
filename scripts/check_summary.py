#!/usr/bin/env python3
"""Nav completeness: every docs/**/*.md is in docs/SUMMARY.md and every
SUMMARY link resolves. Section-parent entries legitimately repeat a child."""
import pathlib
import re
import sys


def main():
    docs = pathlib.Path("docs")
    tree = {p.relative_to(docs).as_posix()
            for p in docs.rglob("*.md") if p.name != "SUMMARY.md"}
    nav = set(re.findall(r"\[[^\]]*\]\(([^)]+)\)", (docs / "SUMMARY.md").read_text(encoding="utf-8")))

    failures = [f"SUMMARY links a missing file: {t}" for t in sorted(nav - tree)]
    failures += [f"page missing from SUMMARY: {t}" for t in sorted(tree - nav)]
    for f in failures:
        print(f)
    print(f"summary: {'FAIL' if failures else 'OK'} ({len(tree)} pages, {len(nav)} nav targets)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
