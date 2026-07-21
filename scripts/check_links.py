#!/usr/bin/env python3
"""Link checker for every *.md in the repo (product/ and node_modules/ excluded).

Default mode: internal relative links, intra-page anchors, and cross-page
anchors must resolve; any failure exits nonzero.
--external: HEAD/GETs each http(s) link with a timeout; 403/429 are reported
as soft (bot walls flake); anything else >=400 or a network error is hard and
exits nonzero. CI runs this mode continue-on-error.
"""
import pathlib
import re
import sys
import urllib.request

EXCLUDE = {"product", "node_modules", ".git"}
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
SOFT_STATUS = {403, 429}


def md_files():
    for p in sorted(pathlib.Path(".").rglob("*.md")):
        if not EXCLUDE & set(p.parts):
            yield p


def github_anchor(heading):
    # GitHub's algorithm: strip formatting, lowercase, drop punctuation except
    # hyphen/underscore, spaces to hyphens.
    text = re.sub(r"`([^`]*)`", r"\1", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_]{1,2}([^*_]+)[*_]{1,2}", r"\1", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors_of(path, cache={}):
    if path not in cache:
        seen = {}
        anchors = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            m = HEADING_RE.match(line)
            if m:
                a = github_anchor(m.group(2))
                n = seen.get(a, 0)
                seen[a] = n + 1
                anchors.add(a if n == 0 else f"{a}-{n}")
        cache[path] = anchors
    return cache[path]


def strip_code(text):
    # Links inside fenced code blocks or inline code are examples, not links.
    text = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    return re.sub(r"`[^`]*`", "", text)


def check_internal():
    failures = []
    for src in md_files():
        for target in LINK_RE.findall(strip_code(src.read_text(encoding="utf-8"))):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path_part, _, anchor = target.partition("#")
            dest = src if not path_part else (src.parent / path_part).resolve()
            if path_part:
                try:
                    dest = pathlib.Path(dest).relative_to(pathlib.Path(".").resolve())
                except ValueError:
                    failures.append(f"{src}: link escapes the repo -> {target}")
                    continue
                if not dest.exists():
                    failures.append(f"{src}: broken link -> {target}")
                    continue
            if anchor and dest.suffix == ".md":
                if anchor not in anchors_of(pathlib.Path(dest)):
                    failures.append(f"{src}: broken anchor -> {target}")
    for f in failures:
        print(f)
    print(f"internal links: {'FAIL' if failures else 'OK'} ({len(failures)} broken)")
    return 1 if failures else 0


def check_external():
    urls = {}
    for src in md_files():
        for target in LINK_RE.findall(strip_code(src.read_text(encoding="utf-8"))):
            if target.startswith(("http://", "https://")):
                urls.setdefault(target, src)
    hard = 0
    for url, src in sorted(urls.items()):
        status = None
        for method in ("HEAD", "GET"):
            req = urllib.request.Request(url, method=method,
                                         headers={"User-Agent": "sessionlayer-docs-linkcheck"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = resp.status
                break
            except urllib.error.HTTPError as e:
                status = e.code
                if method == "GET" or e.code not in (405, 404):
                    break
            except Exception as e:
                status = f"error: {e}"
        if status == 200 or (isinstance(status, int) and status < 400):
            continue
        if isinstance(status, int) and status in SOFT_STATUS:
            print(f"SOFT {status}: {url} ({src})")
        else:
            print(f"HARD {status}: {url} ({src})")
            hard += 1
    print(f"external links: {'FAIL' if hard else 'OK'} ({len(urls)} checked, {hard} hard failures)")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(check_external() if "--external" in sys.argv[1:] else check_internal())
