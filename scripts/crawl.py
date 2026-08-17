#!/usr/bin/env python3
"""
Phase 1 capture: mirror the live Drupal site while it still exists.

The URL list is built from the database rather than by following links, so
coverage is provable: every published node, every forum and taxonomy listing,
every pager page. Link-following would silently miss anything unlinked.

Output:
    mirror/<safe-path>.html    raw response bodies
    mirror/manifest.json       url → status, bytes, path (Phase 6 QA baseline)

Resumable: URLs already present in the manifest are skipped, so an interrupted
run continues where it stopped.

Usage:
    python3 crawl.py php        # just the 16 PHP-bodied nodes
    python3 crawl.py nodes      # all published nodes
    python3 crawl.py listings   # forum / taxonomy / front page, incl. pagers
    python3 crawl.py all
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from dumpq import read_table

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "legacy" / "db"
MIRROR = ROOT / "mirror"
MANIFEST = MIRROR / "manifest.json"

BASE = "https://burnoutaholics.com"
DELAY = 0.7           # gentle on an old server that already struggles
TIMEOUT = 30
RETRIES = 2


def table(name):
    cols, rows = read_table(DB / f"burnoutaholics_com_{name}.sql")
    return {n: k for k, n in enumerate(cols)}, rows


def safe_path(url):
    """Map a URL to a file path under mirror/."""
    p = url[len(BASE):].lstrip("/") or "index"
    p = p.replace("?", "__q__").replace("&", "__a__").replace("=", "__e__")
    return MIRROR / (p + ".html")


def load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def save_manifest(m):
    MIRROR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1, sort_keys=True))


def fetch(url):
    """Return (status, body_bytes). Retries transient failures."""
    for attempt in range(RETRIES + 1):
        try:
            r = subprocess.run(
                ["curl", "-sS", "-L", "--max-time", str(TIMEOUT),
                 "-w", "\n%{http_code}", url],
                capture_output=True, timeout=TIMEOUT + 15,
            )
            out = r.stdout
            nl = out.rfind(b"\n")
            if nl < 0:
                raise ValueError("no status")
            status = out[nl + 1:].decode(errors="replace").strip()
            return status, out[:nl]
        except Exception:
            if attempt == RETRIES:
                return "000", b""
            time.sleep(2 * (attempt + 1))
    return "000", b""


# ---------------------------------------------------------------- URL sets


def urls_php():
    d = json.loads((ROOT / "data" / "needs_crawl.json").read_text())
    return [BASE + x["url"] for x in d]


def urls_nodes():
    ni, nodes = table("node")
    return [
        f"{BASE}/node/{r[ni['nid']]}"
        for r in nodes
        if r[ni["status"]] == "1"
    ]


def urls_listings():
    out = [f"{BASE}/node", f"{BASE}/blog", f"{BASE}/poll",
           f"{BASE}/tracker", f"{BASE}/rss.xml", f"{BASE}/forum"]
    # Front page and section pagers. Drupal shows 10 nodes/page by default;
    # 2,040 published nodes is ~205 pages, so cover generously and let 404s
    # mark the end.
    out += [f"{BASE}/node?page={i}" for i in range(1, 210)]
    out += [f"{BASE}/blog?page={i}" for i in range(1, 120)]

    # Forum containers and forums, from the forum vocabulary.
    fi, forums = table("forum")
    tids = sorted({r[fi["tid"]] for r in forums})
    for tid in tids:
        out.append(f"{BASE}/forum/{tid}")
        out += [f"{BASE}/forum/{tid}?page={i}" for i in range(1, 20)]

    # Taxonomy listings, in all three URL shapes the site actually links to.
    tdi, terms = table("taxonomy_term_data")
    for r in terms:
        tid = r[tdi["tid"]]
        out.append(f"{BASE}/taxonomy/term/{tid}")
        out.append(f"{BASE}/taxonomy/term/{tid}/all")
        out += [f"{BASE}/taxonomy/term/{tid}?page={i}" for i in range(1, 10)]
    return out


SETS = {
    "php": urls_php,
    "nodes": urls_nodes,
    "listings": urls_listings,
}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = list(SETS) if which == "all" else [which]

    urls = []
    for n in names:
        urls += SETS[n]()
    # De-duplicate, keep order.
    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)

    manifest = load_manifest()
    # Retry anything that previously failed outright ("000" = timeout or
    # connection error). Skipping those on resume would quietly bake transient
    # failures into the archive as permanent gaps.
    todo = [
        u for u in ordered
        if u not in manifest or manifest[u].get("status") == "000"
    ]
    print(f"{len(ordered)} urls in set '{which}'; {len(todo)} still to fetch")

    MIRROR.mkdir(parents=True, exist_ok=True)
    done = 0
    for u in todo:
        status, body = fetch(u)
        entry = {"status": status, "bytes": len(body)}
        if status == "200" and body:
            p = safe_path(u)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body)
            entry["path"] = str(p.relative_to(ROOT))
        manifest[u] = entry
        done += 1
        if done % 25 == 0:
            save_manifest(manifest)
            print(f"  {done}/{len(todo)}  last={status}  {u[len(BASE):][:60]}",
                  flush=True)
        time.sleep(DELAY)

    save_manifest(manifest)
    codes = {}
    for v in manifest.values():
        codes[v["status"]] = codes.get(v["status"], 0) + 1
    print(f"\ndone. manifest has {len(manifest)} urls")
    for k in sorted(codes):
        print(f"  {k}: {codes[k]}")


if __name__ == "__main__":
    main()
