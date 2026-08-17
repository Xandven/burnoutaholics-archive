#!/usr/bin/env python3
"""
Internal link check over the built site.

Walks every page in public/, collects root-relative href/src targets, and
reports the ones that do not resolve to a file. Grouped by target so a single
missing page linked from 2,000 pages reads as one problem, not two thousand.
"""
import re
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"

LINK = re.compile(r'(?:href|src)="(/[^"]*)"', re.I)

# `//host/path` is a protocol-relative *external* URL (the AdSense script uses
# one), not a site-root path. Counting those as internal buries the real ones.
EXTERNAL = re.compile(r"^//")


def resolves(target):
    if EXTERNAL.match(target):
        return True
    path = urllib.parse.unquote(target.split("#")[0].split("?")[0])
    if not path or path == "/":
        return (PUBLIC / "index.html").is_file()
    p = PUBLIC / path.lstrip("/")
    return p.is_file() or (p / "index.html").is_file()


def main():
    broken = defaultdict(Counter)
    total_links = 0
    pages = 0

    for f in PUBLIC.rglob("*.html"):
        pages += 1
        try:
            html = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen = set()
        for m in LINK.finditer(html):
            t = m.group(1)
            total_links += 1
            if t in seen:
                continue
            seen.add(t)
            if not resolves(t):
                broken[t][str(f.relative_to(PUBLIC))] += 1

    print(f"pages scanned: {pages}")
    print(f"internal links: {total_links}")
    print(f"distinct broken targets: {len(broken)}")
    print(f"total broken link instances: {sum(sum(c.values()) for c in broken.values())}\n")

    for target, srcs in sorted(broken.items(), key=lambda kv: -sum(kv[1].values()))[:40]:
        n = sum(srcs.values())
        example = next(iter(srcs))
        print(f"  {n:>6}×  {target:<48} e.g. {example}")


if __name__ == "__main__":
    main()
