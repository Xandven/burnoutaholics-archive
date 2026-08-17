#!/usr/bin/env python3
"""
Assemble the Bartik theme's static assets at their original URL paths.

Fidelity comes from reusing Drupal's own stylesheets rather than re-authoring
them, so these are copied verbatim out of `legacy/drupal/`. Paths are preserved
exactly (`/themes/bartik/css/style.css`, …) so any cached or externally-linked
reference still resolves.

Only CSS and images are copied — never PHP, never a whole module directory.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "legacy" / "drupal"
STATIC = ROOT / "static"

# Stylesheets the live page loads, in load order. Source path is relative to
# legacy/drupal/ and is also the destination path under static/.
CSS = [
    "modules/system/system.base.css",
    "modules/system/system.menus.css",
    "modules/system/system.messages.css",
    "modules/system/system.theme.css",
    "modules/aggregator/aggregator.css",
    "modules/comment/comment.css",
    "modules/field/theme/field.css",
    "modules/node/node.css",
    "modules/poll/poll.css",
    "modules/search/search.css",
    "modules/user/user.css",
    "modules/forum/forum.css",
    "sites/all/modules/ctools/css/ctools.css",
    "sites/all/modules/views/css/views.css",
    "themes/bartik/css/layout.css",
    "themes/bartik/css/style.css",
    "themes/bartik/css/print.css",
]

# Bartik ships images referenced from its CSS by relative path.
IMAGE_DIRS = ["themes/bartik/images", "themes/bartik/color"]

# Drupal core ships a handful of shared images that the chrome references
# directly — the feed icon in the footer, pager arrows, the throbber.
MISC_ASSETS = [
    "misc/feed.png",
    "misc/arrow-asc.png",
    "misc/arrow-desc.png",
    "misc/grippie.png",
    "misc/menu-collapsed.png",
    "misc/menu-expanded.png",
    "misc/menu-leaf.png",
    "misc/message-16-error.png",
    "misc/message-16-help.png",
    "misc/message-16-info.png",
    "misc/message-16-ok.png",
    "misc/message-16-warning.png",
    "misc/progress.gif",
    "misc/throbber.gif",
]


def main():
    copied = missing = 0

    for rel in CSS:
        s, d = SRC / rel, STATIC / rel
        if not s.exists():
            print(f"  MISSING {rel}")
            missing += 1
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        copied += 1

    misc = 0
    for rel in MISC_ASSETS:
        s_, d = SRC / rel, STATIC / rel
        if s_.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s_, d)
            misc += 1
    print(f"misc assets copied: {misc}/{len(MISC_ASSETS)}")

    imgs = 0
    for rel in IMAGE_DIRS:
        s = SRC / rel
        if not s.is_dir():
            continue
        for f in s.rglob("*"):
            if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".gif", ".svg"}:
                d = STATIC / rel / f.relative_to(s)
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, d)
                imgs += 1

    print(f"stylesheets copied: {copied}   missing: {missing}")
    print(f"theme images copied: {imgs}")
    print(f"\nNote: /files/** (logo, colour scheme, 92 MB of post assets) is mounted")
    print(f"directly from legacy/files by hugo.toml — not duplicated here.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
