#!/usr/bin/env python3
"""
Check that every asset referenced by the content actually resolves.

Content references paths from three eras: Drupal's /files tree, the pre-Drupal
static site (/videos, /Images, /KML, /clips, ...), and long-dead external hosts.
Only the first is mounted into the build, so this reports what is missing and
where each missing file can be found locally, if anywhere.
"""
import re
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
DATA = ROOT / "data"
FILES = ROOT / "legacy" / "files"
DRUPAL = ROOT / "legacy" / "drupal"
STATIC = ROOT / "static"

REF = re.compile(r'(?:href|src)="(/[^"#?]+)', re.I)

# Routes handled by Hugo, not by a file on disk.
ROUTES = re.compile(
    r"^/(?:node|forum|taxonomy|blog|poll|tracker|faq|clip|search|terms|rss\.xml|messages)"
    r"(?:/|$)", re.I
)


def candidates(path):
    """Where a given URL path might live locally."""
    rel = urllib.parse.unquote(path).lstrip("/")
    yield FILES / rel[len("files/"):] if rel.startswith("files/") else None
    yield DRUPAL / rel
    yield STATIC / rel


def main():
    refs = Counter()
    for p in list(CONTENT.rglob("*.html")) + list((DATA / "comments").glob("*.json")):
        for m in REF.finditer(p.read_text(encoding="utf-8", errors="replace")):
            refs[m.group(1)] += 1

    missing = defaultdict(int)
    found_where = Counter()
    unresolved_prefix = Counter()

    for path, n in refs.items():
        if ROUTES.match(path):
            continue
        hit = None
        for c in candidates(path):
            if c and c.is_file():
                hit = c
                break
        if hit:
            found_where[
                "legacy/files" if FILES in hit.parents else
                ("static" if STATIC in hit.parents else "legacy/drupal")
            ] += n
        else:
            missing[path] += n
            unresolved_prefix["/" + path.lstrip("/").split("/")[0]] += n

    print(f"distinct asset paths referenced: {len(refs)}")
    print("\nresolvable locally:")
    for k, v in found_where.most_common():
        print(f"  {k:<16} {v} references")

    print(f"\nUNRESOLVED: {len(missing)} paths, {sum(missing.values())} references")
    print("by top-level prefix:")
    for k, v in unresolved_prefix.most_common(15):
        print(f"  {k:<20} {v}")

    print("\nsample unresolved paths:")
    for p, n in sorted(missing.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {n:>4}  {p}")


if __name__ == "__main__":
    main()
