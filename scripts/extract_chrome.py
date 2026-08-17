#!/usr/bin/env python3
"""
Lift the page chrome (menus, sidebar blocks, footer) out of a crawled page and
write it into Hugo partials.

Same principle as the CSS: the most faithful reproduction of Bartik's markup is
Bartik's own markup. Hand-retyping the menus would introduce drift. Links inside
the chrome are put through the same rewrite rules as post content, so `?q=`
paths are repaired and dead targets are unwrapped.

Usage:  python3 extract_chrome.py [source.html]
"""
import re
import sys
from pathlib import Path

from rewrite import process as rewrite_links

ROOT = Path(__file__).resolve().parent.parent
MIRROR = ROOT / "mirror"
PARTIALS = ROOT / "layouts" / "partials" / "drupal"

TAG = re.compile(r"<(/?)(div)\b[^>]*>", re.I)


def block(html, marker):
    """Extract a balanced <div> starting at the element containing `marker`."""
    i = html.find(marker)
    if i < 0:
        return None
    start = html.rfind("<div", 0, i)
    if start < 0:
        return None
    depth = 0
    for m in TAG.finditer(html, start):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return html[start:m.end()]
    return None


def by_id(html, el_id):
    return block(html, f'id="{el_id}"')


LI = re.compile(r"<li\b[^>]*>.*?</li>", re.I | re.S)
LI_HREF = re.compile(r'href="([^"]*)"', re.I)
LI_TEXT = re.compile(r"<a\b[^>]*>(.*?)</a>", re.I | re.S)
LI_CLASS = re.compile(r'(<li\b[^>]*\bclass=")([^"]*)(")', re.I)


def dedupe_menu_items(html):
    """Drop repeated menu entries, keeping the first.

    The site's main menu carries "Dominator" twice (menu items 1343 and 420),
    both pointing at /taxonomy/term/13/all — a leftover in the Drupal menu that
    shows up in the header nav and again in the sidebar copy of the same menu.

    These menus are flat (one <ul>, no submenus), so matching <li>…</li> with a
    regex is safe here; it would not be if they nested.
    """
    if not html:
        return html
    items = LI.findall(html)
    if not items:
        return html

    seen, keep = set(), []
    for it in items:
        href = (LI_HREF.search(it) or [None, ""])[1] if LI_HREF.search(it) else ""
        text = LI_TEXT.search(it)
        text = re.sub(r"<[^>]+>", "", text.group(1)).strip() if text else ""
        key = (href, text.lower())
        if key in seen:
            continue
        seen.add(key)
        keep.append(it)

    if len(keep) == len(items):
        return html

    # Removing an item can strand Drupal's first/last classes, which Bartik
    # styles; reapply them to whatever now sits at each end.
    def set_classes(item, first, last):
        def repl(m):
            classes = [c for c in m.group(2).split() if c not in ("first", "last")]
            if first:
                classes.insert(0, "first")
            if last:
                classes.append("last")
            return m.group(1) + " ".join(classes) + m.group(3)

        return LI_CLASS.sub(repl, item, count=1)

    keep = [
        set_classes(it, i == 0, i == len(keep) - 1) for i, it in enumerate(keep)
    ]

    # Replace the whole run of items in one go.
    start = html.find(items[0])
    end = html.rfind(items[-1]) + len(items[-1])
    return html[:start] + "\n".join(keep) + html[end:]


# Menu items to add back. The FAQ page existed on the old site (its Drupal 6
# capture is the reference for layouts/faq/list.html) but had dropped out of the
# Features menu by the time of the crawl.
MENU_ADDITIONS = {
    "menu-features": (
        '<li class="leaf"><a href="/faq" title="Frequently Asked Questions">FAQ</a></li>'
    ),
}


def add_menu_items(name, html):
    """Append an extra <li> to a menu, keeping Drupal's first/last classes sane."""
    extra = MENU_ADDITIONS.get(name)
    if not extra or not html:
        return html
    # The current last item stops being last.
    html = html.replace('class="last leaf"', 'class="leaf"', 1)
    extra = extra.replace('class="leaf"', 'class="last leaf"', 1)
    return html.replace("</ul>", extra + "\n</ul>", 1)


AD_MARKERS = ("googlesyndication", "google_ad_client", "google_ad_slot")
AD_BLOCK_START = re.compile(r'<div\b[^>]*\bid="block--managed-\d+"', re.I)


def strip_ads(html):
    """Remove AdSense blocks from a chrome fragment.

    The site carried three ad slots — a 728x90 in the header, a 160x600 "Support
    US!" in the sidebar, and a 200x200 in the footer — each wrapped in a
    `block--managed-N` div. Removed by decision; the archive carries no ads.

    Works on the whole enclosing block rather than just the <script> tags, so the
    "Support US!" / "Ads by google" heading and the reserved 160x600 gap go with
    them instead of leaving an empty titled box.
    """
    if not html:
        return html
    while True:
        m = AD_BLOCK_START.search(html)
        found = False
        while m:
            start = m.start()
            depth = 0
            end = None
            for t in TAG.finditer(html, start):
                depth += -1 if t.group(1) else 1
                if depth == 0:
                    end = t.end()
                    break
            if end is None:
                break
            candidate = html[start:end]
            if any(k in candidate for k in AD_MARKERS):
                html = html[:start] + html[end:]
                found = True
                break
            m = AD_BLOCK_START.search(html, end)
        if not found:
            return html


def clean(html):
    """Normalise a chrome fragment for reuse as a template partial."""
    if not html:
        return None
    # Absolute references to the old host (e.g. the feed icon) become relative.
    html = re.sub(
        r'(?:https?:)?//(?:www\.)?burnoutaholics\.com(?=/)', "", html, flags=re.I
    )
    html = rewrite_links(html)
    return html.strip() + "\n"


TARGETS = [
    # The three AdSense slots (728x90 header, 160x600 "Support US!" sidebar,
    # 200x200 footer) are deliberately not extracted — the archive is ad-free.
    # strip_ads() also removes the footer one, which is nested inside the footer
    # region rather than standing alone.
    ("main-menu", "main-menu", "main navigation bar"),
    ("menu-community", "block-menu-menu-community", "sidebar: Community menu"),
    ("menu-features", "block-menu-menu-features", "sidebar: Features menu"),
    ("menu-main", "block-system-main-menu", "sidebar: main menu block"),
    ("footer", "footer-wrapper", "footer region"),
    ("triptych", "triptych", "triptych region (forum topics etc.)"),
]


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if src is None:
        cands = sorted(MIRROR.glob("node/*.html"))
        if not cands:
            print("no crawled pages yet — run crawl.py first")
            return 1
        src = cands[0]

    html = src.read_text(encoding="utf-8", errors="replace")
    print(f"source: {src.relative_to(ROOT)}\n")

    PARTIALS.mkdir(parents=True, exist_ok=True)
    written = 0
    for name, el_id, desc in TARGETS:
        frag = add_menu_items(name, dedupe_menu_items(strip_ads(clean(by_id(html, el_id)))))
        if not frag:
            print(f"  -- {name:<16} NOT FOUND ({el_id})")
            continue
        (PARTIALS / f"{name}.html").write_text(frag, encoding="utf-8")
        print(f"  OK {name:<16} {len(frag):>6} bytes  {desc}")
        written += 1

    print(f"\n{written} partials written to {PARTIALS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
