#!/usr/bin/env python3
"""
Copy referenced pre-Drupal assets into static/.

The site predates Drupal, and old posts still link to the original static-site
directories (/videos, /Images, /KML, /clips, ...). Those live in
`legacy/drupal/` and are not covered by the `/files` mount, so without this they
404 in the build.

Only files the content actually references are copied, so orphaned originals do
not end up in every deploy. /videos is excluded entirely — transcode_videos.py
owns it, publishing playable MP4s in place of the .wmv sources.

Usage:  python3 collect_assets.py [--apply]     (default is a dry run)
"""
import shutil
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

from check_assets import CONTENT, DATA, DRUPAL, FILES, REF, ROUTES, STATIC


# Directories under legacy/files that must not be published. `backup_migrate`
# was protected by .htaccess on Apache; nothing on a static host honours that.
FILES_EXCLUDE = {"backup_migrate"}


def sync_files_tree(apply):
    """Copy legacy/files → static/files.

    Previously mounted straight from legacy/ via hugo.toml, which worked locally
    but would have shipped a build with no post images: legacy/ is gitignored, so
    a git-based deploy never sees it. Copying makes the asset tree part of the
    site proper.

    A whole-tree copy rather than a referenced-only one is deliberate: avatars are
    referenced from a JSON field, and the logo, favicon and colour scheme come
    from template params, so a reference scan of href/src alone would miss them.
    """
    copied = skipped = 0
    total = 0
    for src in FILES.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(FILES)
        if rel.parts and rel.parts[0] in FILES_EXCLUDE:
            continue
        dst = STATIC / "files" / rel
        total += src.stat().st_size
        if dst.is_file() and dst.stat().st_size == src.stat().st_size:
            skipped += 1
            continue
        copied += 1
        if apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    print(f"/files tree: {copied} to copy, {skipped} already current, "
          f"{total / 1e6:.0f} MB total")
    return copied


def referenced_paths():
    seen = Counter()
    for p in list(CONTENT.rglob("*.html")) + list((DATA / "comments").glob("*.json")):
        for m in REF.finditer(p.read_text(encoding="utf-8", errors="replace")):
            seen[m.group(1)] += 1
    return seen


def main():
    apply = "--apply" in sys.argv

    sync_files_tree(apply)
    print()

    refs = referenced_paths()

    todo, total_bytes = [], 0
    for path, n in sorted(refs.items()):
        if ROUTES.match(path):
            continue
        rel = urllib.parse.unquote(path).lstrip("/")
        # Already served by the /files mount.
        if rel.startswith("files/") and (FILES / rel[len("files/"):]).is_file():
            continue
        # /videos is handled by transcode_videos.py, which publishes MP4s
        # instead of the unplayable .wmv originals.
        if rel.lower().startswith("videos/"):
            continue
        src = DRUPAL / rel
        if not src.is_file():
            continue
        dst = STATIC / rel
        if dst.is_file() and dst.stat().st_size == src.stat().st_size:
            continue
        todo.append((src, dst, rel, n, src.stat().st_size))
        total_bytes += src.stat().st_size

    by_dir = Counter()
    for _, _, rel, n, size in todo:
        by_dir[rel.split("/")[0]] += size

    print("DRY RUN — nothing copied (pass --apply)" if not apply else "APPLIED")
    print(f"files to copy: {len(todo)}   total: {total_bytes / 1e6:.1f} MB\n")
    for d, size in by_dir.most_common():
        cnt = sum(1 for _, _, rel, _, _ in todo if rel.split("/")[0] == d)
        print(f"  /{d:<12} {cnt:>3} files  {size / 1e6:>7.1f} MB")

    if apply:
        for src, dst, rel, n, size in todo:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        print(f"\ncopied {len(todo)} files into static/")

    # Anything still unresolved after this is genuinely lost or a bad link.
    unresolved = []
    for path, n in refs.items():
        if ROUTES.match(path):
            continue
        rel = urllib.parse.unquote(path).lstrip("/")
        if rel.startswith("files/") and (FILES / rel[len("files/"):]).is_file():
            continue
        if (DRUPAL / rel).is_file() or (STATIC / rel).is_file():
            continue
        unresolved.append((path, n))
    if unresolved:
        print(f"\nstill unresolved ({len(unresolved)}):")
        for p, n in sorted(unresolved, key=lambda kv: -kv[1]):
            print(f"  {n:>3}  {p}")


if __name__ == "__main__":
    main()
