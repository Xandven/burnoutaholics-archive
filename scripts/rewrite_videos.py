#!/usr/bin/env python3
"""
Turn dead .wmv links into working inline video players.

Two link forms exist in the content:

    <a href="/videos/RocketCar.wmv">Rocket Car</a>
    <a href="/node/10?wmv=RocketCar.wmv&title=Rocket%20Car">Rocket Car</a>

The second went to the Clip Viewer, a PHP page that embedded a Windows Media
Player ActiveX control. Neither the page nor the plugin exists any more, and a
static site cannot serve a query-string route, so both forms are replaced with
an inline <video> element pointing at the transcoded MP4.

`<video>` is phrasing content, so substituting it for an inline anchor is valid
even inside a <p> — no block-nesting problem. The original anchor text is kept
inside as fallback content and as the accessible label.

Also writes data/clips.json, which layouts/_default/clips.html renders as the
rebuilt Clip Viewer index at /node/10.

Usage:  python3 rewrite_videos.py [--apply]     (default is a dry run)
"""
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

from rewrite import CONTENT, DATA, split_frontmatter

ROOT = Path(__file__).resolve().parent.parent
MP4 = ROOT / "static" / "videos"

# <a …href="/videos/NAME.wmv"…>TEXT</a>
DIRECT = re.compile(
    r'<a\b[^>]*href="/videos/([^"]+?\.wmv)"[^>]*>(.*?)</a>', re.I | re.S
)
# <a …href="/node/10?wmv=NAME.wmv&title=…"…>TEXT</a>
VIEWER = re.compile(
    r'<a\b[^>]*href="/node/10\?([^"]*)"[^>]*>(.*?)</a>', re.I | re.S
)

stats = Counter()
clips = {}


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def tidy_title(label, rel_wmv):
    """A readable clip title.

    Anchor text is often just the filename ("7_10_Split.wmv"), so drop the
    extension and separators when that is all we have. Real captions written by
    the poster ("Xandu - Perfect on Burning lap") are left alone.
    """
    text = strip_tags(label)
    if not text or text.lower().endswith(".wmv"):
        text = Path(text or rel_wmv).stem
        text = text.replace("_", " ").replace("-", " ").strip()
    return text or Path(rel_wmv).stem


def player(rel_wmv, label):
    """Inline player for a clip, or None if we have no MP4 for it."""
    rel_mp4 = rel_wmv[:-4] + ".mp4"
    if not (MP4 / rel_mp4).is_file():
        return None
    src = "/videos/" + urllib.parse.quote(rel_mp4)
    text = tidy_title(label, rel_wmv)
    clips.setdefault(rel_mp4, text)
    return (
        f'<video class="archived-clip" controls preload="none" '
        f'aria-label="{text}">'
        f'<source src="{src}" type="video/mp4" />'
        f'<a href="{src}">{text}</a>'
        f"</video>"
    )


def convert(html):
    if not html or "/videos/" not in html and "/node/10?" not in html:
        return html

    def direct(m):
        rel = urllib.parse.unquote(m.group(1))
        out = player(rel, m.group(2))
        if out is None:
            stats["no_mp4_direct"] += 1
            return strip_tags(m.group(2)) or m.group(0)
        stats["direct_links_converted"] += 1
        return out

    def viewer(m):
        qs = urllib.parse.parse_qs(m.group(1).replace("&amp;", "&"))
        wmv = (qs.get("wmv") or [None])[0]
        if not wmv:
            return m.group(0)
        label = (qs.get("title") or [None])[0] or m.group(2)
        out = player(urllib.parse.unquote(wmv), label)
        if out is None:
            # Source clip is gone; keep the words, drop the dead link.
            stats["no_mp4_viewer"] += 1
            return strip_tags(m.group(2)) or strip_tags(label)
        stats["viewer_links_converted"] += 1
        return out

    html = DIRECT.sub(direct, html)
    html = VIEWER.sub(viewer, html)
    return html


def main():
    apply = "--apply" in sys.argv
    changed = 0

    for p in sorted(CONTENT.rglob("*.html")):
        text = p.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        new = convert(body)
        if new != body:
            changed += 1
            if apply:
                p.write_text(fm + new, encoding="utf-8")

    for p in sorted((DATA / "comments").glob("*.json")):
        rows = json.loads(p.read_text(encoding="utf-8"))
        dirty = False
        for c in rows:
            nb = convert(c.get("body", ""))
            if nb != c.get("body", ""):
                c["body"] = nb
                dirty = True
        if dirty:
            changed += 1
            if apply:
                p.write_text(
                    json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8"
                )

    # Every MP4 we produced belongs in the index, even if its only reference was
    # a link we just replaced.
    for f in sorted(MP4.rglob("*.mp4")):
        rel = str(f.relative_to(MP4))
        clips.setdefault(rel, Path(rel).stem.replace("_", " "))

    index = [
        {
            "file": rel,
            "src": "/videos/" + urllib.parse.quote(rel),
            "title": title,
            "bytes": (MP4 / rel).stat().st_size,
        }
        for rel, title in sorted(clips.items(), key=lambda kv: kv[1].lower())
    ]
    if apply:
        (DATA / "clips.json").write_text(
            json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8"
        )

    print("DRY RUN — nothing written (pass --apply)" if not apply else "APPLIED")
    print(f"files changed: {changed}")
    for k, v in sorted(stats.items()):
        print(f"  {k:<26} {v}")
    print(f"  clips in index             {len(index)}")


if __name__ == "__main__":
    main()
