#!/usr/bin/env python3
"""
Phase 2 (final step): rewrite inline references inside extracted content.

Operates on href/src attribute values only — never on free text — so post
content cannot be corrupted by an over-eager match. JSON comment files are
loaded and re-serialised structurally rather than patched as text.

Rules
  1. `?q=<path>`  →  `/<path>`
     These are already broken on the live site (they resolve to the front page),
     so this fixes ~390 links rather than preserving a bug.
  2. absolute `http(s)://(www.)burnoutaholics.com/X`  →  `/X`
     Makes the archive host-independent and keeps it working on a preview URL.
  3. Links whose target no longer exists on a static site are unwrapped: the
     anchor is replaced by its own text, so the sentence still reads correctly
     but there is no dead link. Applies to /user/*, /comment/reply/*,
     /node/add/*, and the removed node 2120.
  4. Everything else is left alone. /files, /node/N, /forum/N and /taxonomy/*
     are all URLs the static site preserves.

Usage:  python3 rewrite.py [--apply]     (default is a dry run)
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
DATA = ROOT / "data"

SELF_HOST = re.compile(r"^(?:https?:)?//(?:www\.)?burnoutaholics\.com(?=/|$)", re.I)
QUERY_PATH = re.compile(r"^/?\?q=([^&#]*)(.*)$")

# Targets that cannot exist on a static, read-only archive.
# Routes with no static equivalent. Beyond the obvious account pages, this
# covers modules that are gone: blog-by-user listings (/blog/<uid>), the faq
# module's category pages, userpoints, private messages and the feed aggregator.
# Each was a live page once; linking to a 404 is worse than plain text.
DEAD = re.compile(
    r"^/(?:user(?:/|$)|comment/reply(?:/|$)|node/add(?:/|$)|node/2120(?:$|[/#?])"
    r"|logout|admin(?:/|$)|blog/\d+|faq/\d+|userpoints(?:/|$)|messages(?:/|$)"
    r"|aggregator(?:/|$))",
    re.I,
)

ATTR = re.compile(r'(?P<pre>\b(?:href|src)=")(?P<url>[^"]*)(?P<post>")', re.I)
ANCHOR = re.compile(r'<a\b[^>]*\bhref="(?P<url>[^"]*)"[^>]*>(?P<text>.*?)</a>',
                    re.I | re.S)

stats = Counter()


def rewrite_url(u):
    """Return the rewritten URL, or None to leave it untouched."""
    orig = u
    # Stray whitespace inside the attribute (`href="/node/4 "`) is an authoring
    # typo that appears a handful of times; browsers mostly cope, link checkers
    # and some servers do not.
    u = u.strip()
    m = SELF_HOST.match(u)
    if m:
        u = u[m.end():] or "/"
        stats["absolute_to_relative"] += 1

    m = QUERY_PATH.match(u)
    if m:
        path, rest = m.group(1), m.group(2)
        if path:
            # Any surviving parameters must be re-attached with `?`, not glued
            # straight on: `?q=node/10&wmv=X` is `/node/10?wmv=X`, never
            # `/node/10&wmv=X`. (Clip-viewer links in old posts hit this.)
            # In real markup the separator is usually the HTML entity, not a
            # bare ampersand, so check the entity form first — otherwise
            # `&amp;wmv=` turns into the nonsense `?amp;wmv=`.
            if rest.startswith("&amp;"):
                rest = "?" + rest[5:]
            elif rest.startswith("&"):
                rest = "?" + rest[1:]
            u = "/" + path.lstrip("/") + rest
            stats["q_param_fixed"] += 1

    return u if u != orig else None


def unwrap_dead(html):
    """Replace anchors pointing at now-nonexistent targets with their text."""

    def repl(m):
        url = m.group("url")
        stripped = SELF_HOST.sub("", url)
        qm = QUERY_PATH.match(stripped)
        if qm and qm.group(1):
            stripped = "/" + qm.group(1).lstrip("/")
        if DEAD.match(stripped or "/"):
            stats["dead_links_unwrapped"] += 1
            return m.group("text")
        return m.group(0)

    return ANCHOR.sub(repl, html)


def process(html):
    html = unwrap_dead(html)

    def repl(m):
        new = rewrite_url(m.group("url"))
        if new is None:
            return m.group(0)
        return m.group("pre") + new + m.group("post")

    return ATTR.sub(repl, html)


def split_frontmatter(text):
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---\n", 3)
    if end < 0:
        return "", text
    return text[: end + 5], text[end + 5:]


def main():
    apply = "--apply" in sys.argv
    changed_files = 0

    for p in sorted(CONTENT.rglob("*.html")):
        text = p.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        new = process(body)
        if new != body:
            changed_files += 1
            if apply:
                p.write_text(fm + new, encoding="utf-8")

    for p in sorted((DATA / "comments").glob("*.json")):
        rows = json.loads(p.read_text(encoding="utf-8"))
        dirty = False
        for c in rows:
            nb = process(c.get("body", ""))
            if nb != c.get("body", ""):
                c["body"] = nb
                dirty = True
        if dirty:
            changed_files += 1
            if apply:
                p.write_text(
                    json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8"
                )

    print("DRY RUN — nothing written (pass --apply to write)" if not apply
          else "APPLIED")
    print(f"files changed: {changed_files}")
    for k, v in sorted(stats.items()):
        print(f"  {k:<24} {v}")


if __name__ == "__main__":
    main()
