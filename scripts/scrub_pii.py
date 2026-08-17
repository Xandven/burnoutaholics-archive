#!/usr/bin/env python3
"""
Remove personal email addresses from published content.

Comment `mail`/`hostname` columns never leave extract.py, but addresses typed
*into* post and comment bodies survive the filter pipeline — and `filter_url`
helpfully turns them into clickable `mailto:` links, which is exactly what
address harvesters look for.

This runs as a pipeline step rather than a one-off edit, because build_content.sh
regenerates content/ from the dump; a manual scrub would silently disappear on
the next rebuild.

Allowlist, not blocklist: organisational addresses (the site's own, Criterion,
EA, Microsoft, Edge) are editorially meaningful and stay. Everything else is
treated as personal and redacted, so an address that only appears after a future
re-extraction is caught too.

Usage:  python3 scrub_pii.py [--apply]     (default is a dry run)
"""
import json
import re
import sys
from collections import Counter

from rewrite import CONTENT, DATA, split_frontmatter

# Organisational addresses — published deliberately, not personal data.
ALLOW = {
    "admin@burnoutaholics.com",
    "clips@burnoutaholics.com",
    "mailbag@criteriongames.com",
    "customerservice@ea.com",
    "backcomp@microsoft.com",
    "xlmail@microsoft.com",
    "edge@futurenet.co.uk",
}

REDACTION = "[email address removed]"

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MAILTO_ANCHOR = re.compile(
    r'<a\b[^>]*href="mailto:([^"?]+)[^"]*"[^>]*>(.*?)</a>', re.I | re.S
)

removed = Counter()
unwrapped = Counter()


def allowed(addr):
    return addr.strip().lower() in {a.lower() for a in ALLOW}


def scrub(html):
    if not html:
        return html

    # Anchors first: replacing the address alone would leave a live mailto: href.
    def anchor(m):
        addr = m.group(1)
        if allowed(addr):
            return m.group(0)
        if not EMAIL.fullmatch(addr.strip()):
            # Not actually an address. Drupal's filter_url linkified things
            # people merely typed — "W@W", "b@ll\"cks" — and redacting those
            # would rewrite their words. Unwrap to the original text instead.
            unwrapped[addr] += 1
            return m.group(2)
        removed[addr] += 1
        return REDACTION

    html = MAILTO_ANCHOR.sub(anchor, html)

    def bare(m):
        addr = m.group(0)
        if allowed(addr):
            return addr
        removed[addr] += 1
        return REDACTION

    return EMAIL.sub(bare, html)


def main():
    apply = "--apply" in sys.argv
    changed = 0

    for p in sorted(CONTENT.rglob("*.html")):
        text = p.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        new = scrub(body)
        if new != body:
            changed += 1
            if apply:
                p.write_text(fm + new, encoding="utf-8")

    for p in sorted((DATA / "comments").glob("*.json")):
        rows = json.loads(p.read_text(encoding="utf-8"))
        dirty = False
        for c in rows:
            nb = scrub(c.get("body", ""))
            if nb != c.get("body", ""):
                c["body"] = nb
                dirty = True
        if dirty:
            changed += 1
            if apply:
                p.write_text(
                    json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8"
                )

    print("DRY RUN — nothing written (pass --apply)" if not apply else "APPLIED")
    print(f"files changed: {changed}")
    print(f"addresses redacted: {sum(removed.values())} occurrences, "
          f"{len(removed)} distinct")
    if unwrapped:
        print(f"non-addresses unwrapped (kept as text): {sum(unwrapped.values())}")
    for a, n in removed.most_common():
        # Show only the domain — printing the addresses would defeat the point.
        print(f"  {n:>3}×  …@{a.split('@')[-1]}")


if __name__ == "__main__":
    main()
