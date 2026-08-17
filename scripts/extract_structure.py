#!/usr/bin/env python3
"""
Generate listing pages: forums and taxonomy terms.

Drupal serves these from database queries. A static site needs a real page per
listing, so this writes one stub content file per forum and per taxonomy term,
each carrying `url:` so the original path is preserved exactly
(`/forum/22`, `/taxonomy/term/13`), plus the JSON the templates render from.

Runs after extract.py — it reuses the same tables and the same mojibake repair.

Output:
    content/listing/forum-<tid>.html      stub → /forum/<tid>
    content/listing/forum-index.html      stub → /forum
    content/listing/term-<tid>.html       stub → /taxonomy/term/<tid>
    data/forums.json                      container/forum tree with counts
    data/forum_topics/<tid>.json          topics per forum
    data/terms.json                       tid → name, vocabulary
    data/term_nodes/<tid>.json            nodes carrying each term
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import drupal_filters as F
from dumpq import read_table
from extract import EXCLUDED_NODES, iso, yaml_str
from rewrite import process as rewrite_links

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "legacy" / "db"
CONTENT = ROOT / "content"
DATA = ROOT / "data"

FORUM_VID = "5"          # the "Forums" vocabulary
FORUM_CONTAINER = "21"   # "BurnoutAholics Forums"

# Drupal's defaults: forum_per_page = 25, taxonomy term pages = 10.
FORUM_PER_PAGE = 25
TERM_PER_PAGE = 10


def paged_stubs(base_url, count, per_page, write):
    """Emit one stub per page of a listing.

    Hugo cannot paginate a `page` kind, and these listings are driven by data
    files rather than by Pages, so pagination is materialised here: page 1 keeps
    the original URL, later pages follow Hugo's /page/N convention.
    """
    pages = max(1, -(-count // per_page))
    for n in range(1, pages + 1):
        url = base_url if n == 1 else f"{base_url}/page/{n}"
        write(n, pages, url)
    return pages


def table(name):
    cols, rows = read_table(DB / f"burnoutaholics_com_{name}.sql")
    return {n: k for k, n in enumerate(cols)}, rows


def stub(path, title, url, kind, extra=None, aliases=()):
    fm = [
        "---",
        f"title: {yaml_str(title)}",
        f"url: {url}",
        f"layout: {kind}",
        "draft: false",
    ]
    if aliases:
        fm.append("aliases:")
        fm += [f"  - {a}" for a in sorted(set(aliases))]
    for k, v in (extra or {}).items():
        fm.append(f"{k}: {v if isinstance(v, (int, float)) else yaml_str(str(v))}")
    fm.append("---")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(fm) + "\n", encoding="utf-8")


# Old links use a two-segment taxonomy form, e.g. /taxonomy/term/20/35. On the
# live site the trailing segment is ignored and term 20's page is served, so we
# collect the variants actually linked and register them as aliases.
TERM_VARIANT = re.compile(r"/taxonomy/term/(\d+)/(\d+)")


def term_url_variants():
    found = defaultdict(set)
    roots = [CONTENT, ROOT / "layouts" / "partials" / "drupal"]
    for root in roots:
        if not root.exists():
            continue
        for f in root.rglob("*.html"):
            for m in TERM_VARIANT.finditer(
                f.read_text(encoding="utf-8", errors="replace")
            ):
                found[m.group(1)].add(f"/taxonomy/term/{m.group(1)}/{m.group(2)}")
    return found


def main():
    ni, nodes = table("node")
    ui, users = table("users")
    ti, terms = table("taxonomy_term_data")
    hi, hier = table("taxonomy_term_hierarchy")
    vi, vocabs = table("taxonomy_vocabulary")
    xi, tindex = table("taxonomy_index")
    fi, findex = table("forum_index")

    username = {r[ui["uid"]]: F.repair_mojibake(r[ui["name"]]) for r in users}
    node_by_id = {r[ni["nid"]]: r for r in nodes}
    parent = {r[hi["tid"]]: r[hi["parent"]] for r in hier}
    vocab_name = {r[vi["vid"]]: F.repair_mojibake(r[vi["name"]]) for r in vocabs}

    term = {}
    for r in terms:
        term[r[ti["tid"]]] = {
            "tid": r[ti["tid"]],
            "vid": r[ti["vid"]],
            "name": F.repair_mojibake(r[ti["name"]]),
            # Forum descriptions are stored HTML and contain the same legacy
            # `?q=` links as post bodies, so they get the same rewrite.
            "description": rewrite_links(
                F.repair_mojibake(r[ti["description"]] or "")
            ),
            "vocabulary": vocab_name.get(r[ti["vid"]], ""),
            "parent": parent.get(r[ti["tid"]], "0"),
            "weight": int(r[ti["weight"]] or 0),
        }

    listing = CONTENT / "listing"
    listing.mkdir(parents=True, exist_ok=True)
    # Stubs each carry their own `url:`, so the holding section itself must
    # never render — otherwise /listing/ shows up as a stray page.
    (listing / "_index.html").write_text(
        '---\ntitle: "Listings"\nbuild:\n  render: never\n  list: never\n---\n',
        encoding="utf-8")

    # The faq section renders through layouts/faq/list.html; give it a title.
    faq_dir = CONTENT / "faq"
    faq_dir.mkdir(parents=True, exist_ok=True)
    (faq_dir / "_index.html").write_text(
        '---\ntitle: "Frequently Asked Questions"\nurl: /faq\n---\n',
        encoding="utf-8")

    # ---------------------------------------------------------------- forums
    topics = defaultdict(list)
    for r in findex:
        nid = r[fi["nid"]]
        if nid in EXCLUDED_NODES or nid not in node_by_id:
            continue
        n = node_by_id[nid]
        if n[ni["status"]] != "1":
            continue
        topics[r[fi["tid"]]].append(
            {
                "nid": nid,
                "title": F.repair_mojibake(r[fi["title"]]),
                "author": username.get(n[ni["uid"]], "Anonymous"),
                "created": iso(r[fi["created"]]),
                "last_post": iso(r[fi["last_comment_timestamp"]]),
                "replies": int(r[fi["comment_count"]] or 0),
                "sticky": r[fi["sticky"]] == "1",
            }
        )
    for v in topics.values():
        # Drupal orders forum topics sticky first, then most recent activity.
        v.sort(key=lambda t: (not t["sticky"], t["last_post"] or ""), reverse=False)
        v.sort(key=lambda t: (t["sticky"], t["last_post"] or ""), reverse=True)

    forums = [t for t in term.values()
              if t["vid"] == FORUM_VID and t["tid"] != FORUM_CONTAINER]
    tree = []
    # Drupal orders forums by term weight, then name — not by tid. Verified
    # against the live /forum page: 22, 40, 38, 39, 23, 55.
    for f in sorted(forums, key=lambda t: (t["weight"], t["name"])):
        tl = topics.get(f["tid"], [])
        tree.append({
            **f,
            "topics": len(tl),
            "posts": len(tl) + sum(t["replies"] for t in tl),
            "last_post": max((t["last_post"] or "" for t in tl), default=None),
        })

    (DATA / "forums.json").write_text(
        json.dumps({"container": term.get(FORUM_CONTAINER), "forums": tree},
                   indent=1, ensure_ascii=False), encoding="utf-8")

    (DATA / "forum_topics").mkdir(parents=True, exist_ok=True)
    for tid, tl in topics.items():
        (DATA / "forum_topics" / f"{tid}.json").write_text(
            json.dumps(tl, indent=1, ensure_ascii=False), encoding="utf-8")

    # Static search page, backed by the Pagefind index built after Hugo runs.
    stub(listing / "search.html", "Search", "/search/", "search")

    stub(listing / "forum-index.html", "Forums", "/forum", "forum-index",
         aliases=[f"/forum/{FORUM_CONTAINER}"])
    forum_pages = 0
    for f in tree:
        def write(n, total, url, f=f):
            name = f"forum-{f['tid']}" + ("" if n == 1 else f"-p{n}")
            stub(listing / f"{name}.html", f["name"], url, "forum",
                 {"tid": f["tid"], "description": f["description"],
                  "page": n, "pages": total, "per_page": FORUM_PER_PAGE})
        forum_pages += paged_stubs(f"/forum/{f['tid']}", f["topics"],
                                   FORUM_PER_PAGE, write)

    # -------------------------------------------------------------- taxonomy
    term_nodes = defaultdict(list)
    for r in tindex:
        nid = r[xi["nid"]]
        if nid in EXCLUDED_NODES or nid not in node_by_id:
            continue
        n = node_by_id[nid]
        if n[ni["status"]] != "1":
            continue
        term_nodes[r[xi["tid"]]].append({
            "nid": nid,
            "title": F.repair_mojibake(n[ni["title"]]),
            "type": n[ni["type"]],
            "author": username.get(n[ni["uid"]], "Anonymous"),
            "created": iso(n[ni["created"]]),
        })
    for v in term_nodes.values():
        v.sort(key=lambda x: x["created"] or "", reverse=True)

    (DATA / "term_nodes").mkdir(parents=True, exist_ok=True)
    variants = term_url_variants()
    used = 0
    # Every term gets a page, including those with no content: they are linked
    # from menus and old posts, and an empty listing beats a 404.
    for tid in term:
        ns = term_nodes.get(tid, [])
        (DATA / "term_nodes" / f"{tid}.json").write_text(
            json.dumps(ns, indent=1, ensure_ascii=False), encoding="utf-8")
        t = term[tid]

        def write(n, total, url, tid=tid, t=t):
            name = f"term-{tid}" + ("" if n == 1 else f"-p{n}")
            stub(listing / f"{name}.html", t["name"], url, "termlist",
                 {"tid": tid, "vocabulary": t["vocabulary"],
                  "description": t["description"],
                  "page": n, "pages": total, "per_page": TERM_PER_PAGE},
                 )

        paged_stubs(f"/taxonomy/term/{tid}", len(ns), TERM_PER_PAGE, write)
        # `/taxonomy/term/N/all` is linked from the site's own navigation.
        stub(listing / f"term-{tid}-all.html", t["name"],
             f"/taxonomy/term/{tid}/all", "termlist",
             {"tid": tid, "vocabulary": t["vocabulary"],
              "description": t["description"],
              "page": 1, "pages": 1, "per_page": 100000})
        used += 1

    # ------------------------------------------------------------- tracker
    # "Recent posts" — linked from the main navigation. Drupal ranked by latest
    # activity (post or comment); we have last_comment via node_comment_statistics
    # where available, falling back to the node's own changed date.
    si, stats_rows = table("node_comment_statistics")
    last_activity = {r[si["nid"]]: r[si["last_comment_timestamp"]] for r in stats_rows}
    comment_total = {r[si["nid"]]: int(r[si["comment_count"]] or 0) for r in stats_rows}

    recent = []
    for r in nodes:
        nid = r[ni["nid"]]
        if nid in EXCLUDED_NODES or r[ni["status"]] != "1":
            continue
        recent.append({
            "nid": nid,
            "title": F.repair_mojibake(r[ni["title"]]),
            "type": r[ni["type"]],
            "author": username.get(r[ni["uid"]], "Anonymous"),
            "created": iso(r[ni["created"]]),
            "last_activity": iso(last_activity.get(nid, r[ni["changed"]])),
            "replies": comment_total.get(nid, 0),
        })
    recent.sort(key=lambda x: x["last_activity"] or "", reverse=True)
    (DATA / "tracker.json").write_text(
        json.dumps(recent, indent=1, ensure_ascii=False), encoding="utf-8")

    def write_tracker(n, total, url):
        name = "tracker" + ("" if n == 1 else f"-p{n}")
        stub(listing / f"{name}.html", "Recent posts", url, "tracker",
             {"page": n, "pages": total, "per_page": TERM_PER_PAGE})

    tracker_pages = paged_stubs("/tracker", len(recent), TERM_PER_PAGE, write_tracker)

    # ---------------------------------------------- term intersections (A/B)
    # Old menu links use Drupal 6's two-tid AND form, e.g. /taxonomy/term/20/35
    # ("GCA 08") and /taxonomy/term/36/4 ("CRASH!"). The page lists nodes
    # carrying *both* terms and takes its title from the first — confirmed
    # against the Wayback capture of /taxonomy/term/20/35, which listed exactly
    # the four nodes in term 20 ∩ term 35.
    #
    # Drupal 7 lost this: the live site ignores the second tid and serves term A,
    # which is why the "GCA 08" and "CRASH!" menu items had stopped working.
    pairs = 0
    for a, urls in variants.items():
        for url in urls:
            b = url.rsplit("/", 1)[-1]
            if a not in term or b not in term:
                continue
            inter = [n for n in term_nodes.get(a, [])
                     if n["nid"] in {x["nid"] for x in term_nodes.get(b, [])}]
            key = f"{a}-{b}"
            (DATA / "term_nodes" / f"{key}.json").write_text(
                json.dumps(inter, indent=1, ensure_ascii=False), encoding="utf-8")
            stub(listing / f"term-{key}.html", term[a]["name"], url, "termlist",
                 {"tid": key, "vocabulary": term[a]["vocabulary"],
                  "description": term[a]["description"],
                  "filter_a": term[a]["name"], "filter_b": term[b]["name"],
                  "page": 1, "pages": 1, "per_page": 10000})
            pairs += 1
    print(f"term intersections: {pairs}")

    (DATA / "terms.json").write_text(
        json.dumps(term, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"forums:         {len(tree)} (+1 index)")
    print(f"forum topics:   {sum(len(v) for v in topics.values())}")
    print(f"taxonomy terms: {used} with content, of {len(term)} total")
    print(f"term→node rows: {sum(len(v) for v in term_nodes.values())}")
    print(f"tracker:        {len(recent)} posts over {tracker_pages} pages")


if __name__ == "__main__":
    main()
