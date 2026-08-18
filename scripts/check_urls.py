#!/usr/bin/env python3
"""
Phase 5/6 check: does every URL that worked on the live site still work?

The Phase 1 crawl recorded 3,090 URLs with their HTTP status. Anything that
returned 200 then and does not resolve now is a link we have broken — twenty
years of inbound links point at these.

Resolution counts if the built site has a matching file, or a redirect rule in
static/_redirects or netlify.toml covers it.
"""
import json
import re
import urllib.parse
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
MANIFEST = ROOT / "mirror" / "manifest.json"
BASE = "https://burnoutaholics.com"


def load_redirect_prefixes():
    """Literal paths and prefixes covered by redirect rules."""
    literal, prefixes = set(), []
    rd = ROOT / "static" / "_redirects"
    if rd.exists():
        for line in rd.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            src = line.split()[0]
            (prefixes.append(src[:-1]) if src.endswith("*") else literal.add(src))
    nt = ROOT / "netlify.toml"
    if nt.exists():
        for m in re.finditer(r'from\s*=\s*"([^"]+)"', nt.read_text(encoding="utf-8")):
            src = m.group(1)
            (prefixes.append(src[:-1]) if src.endswith("*") else literal.add(src))
    return literal, prefixes


def main():
    if not MANIFEST.exists():
        print("no crawl manifest — run scripts/crawl.py first")
        return 1

    manifest = json.loads(MANIFEST.read_text())
    literal, prefixes = load_redirect_prefixes()

    def resolves(path):
        clean = urllib.parse.unquote(path.split("#")[0].split("?")[0])
        if clean in literal or any(clean.startswith(p) for p in prefixes):
            return True
        if clean in ("", "/"):
            return (PUBLIC / "index.html").is_file()
        p = PUBLIC / clean.lstrip("/")
        return p.is_file() or (p / "index.html").is_file()

    was_ok = [u for u, v in manifest.items() if v.get("status") == "200"]
    broken, kinds = [], Counter()
    for u in was_ok:
        path = u[len(BASE):] if u.startswith(BASE) else u
        # Query-string pagers (?page=N) are served at /page/N now; the query form
        # cannot be expressed as a static file and is handled separately.
        if "?" in path:
            kinds["query-string URL (pager)"] += 1
            continue
        if not resolves(path):
            broken.append(path)

    print(f"crawled URLs that returned 200: {len(was_ok)}")
    print(f"  skipped (query-string):       {kinds['query-string URL (pager)']}")
    print(f"  checked:                      {len(was_ok) - kinds['query-string URL (pager)']}")
    print(f"  BROKEN NOW:                   {len(broken)}")
    for b in sorted(broken)[:40]:
        print(f"    {b}")
    if len(broken) > 40:
        print(f"    … and {len(broken) - 40} more")
    return 0


if __name__ == "__main__":
    main()
