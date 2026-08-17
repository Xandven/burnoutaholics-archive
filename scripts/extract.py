#!/usr/bin/env python3
"""
Phase 2: extract Drupal content from the dump into static-site source files.

Output layout:
    content/<type>/<nid>.html     one file per node, YAML frontmatter + rendered HTML
    data/comments/<nid>.json      comments for that node, personal data removed
    data/polls/<nid>.json         frozen poll results
    data/needs_crawl.json         nodes whose body is executable PHP

Bodies are emitted as HTML rather than Markdown deliberately: the brief requires
the new site to look identical to the old one, and an HTML→Markdown→HTML round
trip loses tables, <font>, inline markup and embeds. Hugo passes `.html` content
files through untouched.

Personal data (comment emails, IP addresses, user emails and password hashes) is
dropped here, at the source, so it can never reach an intermediate file.
"""
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import drupal_filters as F
from dumpq import read_table

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "legacy" / "db"
CONTENT = ROOT / "content"
DATA = ROOT / "data"

PHP_FORMAT = "2"

# Nodes deliberately not carried into the static site.
#   2120 "Hall of Shame - Spammer directory" — 86 email addresses and 31 IP
#        addresses published alongside an accusation of spamming. Republishing it
#        as a permanent, re-indexed static page is not defensible under GDPR, and
#        filter_url would turn the addresses into harvestable mailto: links.
#   3639 "Feedback" — the contact form, dropped by decision. Its body is empty:
#        the form came entirely from the webform module, which is absent from
#        legacy/drupal. Left in, it would be a blank page titled "Feedback" —
#        and it carries promote=1, so it would appear on the front page.
EXCLUDED_NODES = {"2120", "3639"}

# Nodes that get a bespoke template instead of the generic one. node/4's PHP
# gamertag generator is reimplemented client-side (see layouts/_default/gamertag.html).
SPECIAL_LAYOUTS = {
    "4": "gamertag",
    # node/10 was the Clip Viewer: a PHP page driven by ?wmv= query
    # parameters around a Windows Media ActiveX embed. Rebuilt as a
    # static index of the transcoded clips.
    "10": "clips",
}


def table(name):
    p = DB / f"burnoutaholics_com_{name}.sql"
    if not p.exists():
        return [], []
    cols, rows = read_table(p)
    idx = {n: k for k, n in enumerate(cols)}
    return idx, rows


def iso(ts):
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def yaml_str(s):
    """Quote a scalar for YAML safely enough for titles written by humans."""
    if s is None:
        return '""'
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    # YAML forbids C0/C1 control characters. Twenty years of copy-paste leaves
    # stray ones behind (e.g. \x9d from a half-repaired smart quote), and they
    # abort the whole build with an unhelpful "control characters are not
    # allowed" at line 1. Strip them as a backstop even after mojibake repair.
    s = "".join(c for c in s if not (ord(c) < 32 or 0x7F <= ord(c) <= 0x9F))
    return f'"{s}"'


def main():
    print("reading dump…")
    ni, nodes = table("node")
    bi, bodies = table("field_data_body")
    ui, users = table("users")
    ti, tindex = table("taxonomy_index")
    tdi, terms = table("taxonomy_term_data")
    ci, comments = table("comment")
    cbi, cbodies = table("field_data_comment_body")
    pi, polls = table("poll")
    pci, pchoices = table("poll_choice")
    fi, forums = table("forum")
    nci, counters = table("node_counter")

    # --- lookup tables -----------------------------------------------------
    # Usernames only. Never carry mail/pass/init out of this function.
    username = {r[ui["uid"]]: F.repair_mojibake(r[ui["name"]]) for r in users}
    username.setdefault("0", "Anonymous")

    # Comment avatars: users.picture is an fid into file_managed, whose uri is a
    # plain relative path on this site (`files/pictures/picture-607.jpg`) rather
    # than the Drupal-standard `public://` scheme.
    fmi, fmrows = table("file_managed")
    file_uri = {r[fmi["fid"]]: r[fmi["uri"]] for r in fmrows}
    avatar = {}
    for r in users:
        uri = file_uri.get(r[ui["picture"]])
        if uri:
            avatar[r[ui["uid"]]] = "/" + uri.lstrip("/")

    termname = {r[tdi["tid"]]: F.repair_mojibake(r[tdi["name"]]) for r in terms}

    # Term links must point at the original /taxonomy/term/<tid> paths, so carry
    # the tid alongside the name rather than slugifying the name.
    node_terms = defaultdict(list)
    for r in tindex:
        tid = r[ti["tid"]]
        t = termname.get(tid)
        if t and not any(x["tid"] == tid for x in node_terms[r[ti["nid"]]]):
            node_terms[r[ti["nid"]]].append({"tid": tid, "name": t})

    body_of = {r[bi["entity_id"]]: r for r in bodies}
    views = {r[nci["nid"]]: r[nci["totalcount"]] for r in counters}
    forum_tid = {r[fi["nid"]]: r[fi["tid"]] for r in forums}

    cbody_of = {r[cbi["entity_id"]]: r for r in cbodies}

    # --- comments ----------------------------------------------------------
    by_node = defaultdict(list)
    dropped_pii = 0
    for r in comments:
        if r[ci["status"]] != "1":
            continue  # 27 unapproved rows — excluded by decision
        cid = r[ci["cid"]]
        cb = cbody_of.get(cid)
        raw = cb[cbi["comment_body_value"]] if cb else ""
        fmt = cb[cbi["comment_body_format"]] if cb else "1"
        try:
            html = F.render(F.repair_mojibake(raw), fmt)
        except ValueError:
            html = ""  # PHP-format comment; vanishingly rare, keep it empty
        uid = r[ci["uid"]]
        # `name` is the anonymous poster's chosen name; mail/hostname are dropped.
        author = username.get(uid) if uid != "0" else F.repair_mojibake(r[ci["name"]])
        if r[ci["mail"]] or r[ci["hostname"]]:
            dropped_pii += 1
        by_node[r[ci["nid"]]].append(
            {
                "cid": cid,
                "pid": r[ci["pid"]],
                "thread": r[ci["thread"]],
                "subject": F.repair_mojibake(r[ci["subject"]]),
                "author": author or "Anonymous",
                "uid": uid,
                "avatar": avatar.get(uid),
                "created": iso(r[ci["created"]]),
                "body": html,
            }
        )
    for v in by_node.values():
        v.sort(key=lambda c: (c["thread"] or "", int(c["cid"])))

    # --- polls -------------------------------------------------------------
    poll_choices = defaultdict(list)
    for r in pchoices:
        poll_choices[r[pci["nid"]]].append(
            {
                "text": F.repair_mojibake(r[pci["chtext"]]),
                "votes": int(r[pci["chvotes"]] or 0),
                "weight": int(r[pci["weight"]] or 0),
            }
        )
    poll_active = {r[pi["nid"]]: r[pi["active"]] for r in polls}

    # --- write -------------------------------------------------------------
    for d in (CONTENT, DATA / "comments", DATA / "polls"):
        d.mkdir(parents=True, exist_ok=True)

    stats = defaultdict(int)
    needs_crawl = []

    for r in nodes:
        nid = r[ni["nid"]]
        if nid in EXCLUDED_NODES:
            stats["excluded"] += 1
            continue
        ntype = r[ni["type"]]
        status = r[ni["status"]]
        title = F.repair_mojibake(r[ni["title"]])

        b = body_of.get(nid)
        fmt = b[bi["body_format"]] if b else "1"
        # Bodies and summaries need the same selective mojibake repair as titles
        # and comments — field_data_body is utf8, but content copy-pasted into it
        # over 20 years carries plenty of double-encoded punctuation.
        raw = F.repair_mojibake((b[bi["body_value"]] if b else "") or "")
        summary = F.repair_mojibake((b[bi["body_summary"]] if b else "") or "")

        if fmt == PHP_FORMAT and "<?" in raw:
            # Executable PHP: its output cannot be derived from the database.
            # The prose written above the code block can be, though — most of
            # these pages open with a human-written introduction, and throwing it
            # away loses real content for no reason.
            needs_crawl.append(
                {"nid": nid, "title": title, "type": ntype, "url": f"/node/{nid}"}
            )
            prefix = raw[: raw.index("<?")].strip()
            html = F.render(prefix, "3") if prefix else ""
            if prefix:
                stats["php_intro_kept"] += 1
            stats["php_deferred"] += 1
        else:
            # node/1219 is tagged format 2 but contains no PHP — treat as Full HTML.
            eff = "3" if fmt == PHP_FORMAT else fmt
            html = F.render(raw, eff)
            stats["rendered"] += 1

        fm = [
            "---",
            f"title: {yaml_str(title)}",
            f"nid: {nid}",
            f"type: {yaml_str(ntype)}",
            f"url: /node/{nid}",
            f"date: {iso(r[ni['created']])}",
            f"lastmod: {iso(r[ni['changed']])}",
            f"author: {yaml_str(username.get(r[ni['uid']], 'Anonymous'))}",
            f"draft: {'false' if status == '1' else 'true'}",
            # Drupal's front page lists promoted nodes, sticky ones first.
            # Without these the front page cannot be reproduced faithfully.
            f"promote: {'true' if r[ni['promote']] == '1' else 'false'}",
            f"sticky: {'true' if r[ni['sticky']] == '1' else 'false'}",
            f"weight: {0 if r[ni['sticky']] != '1' else -1}",
        ]
        if summary.strip():
            fm.append(f"summary: {yaml_str(re.sub(r'<[^>]+>', '', summary).strip())}")
        if node_terms.get(nid):
            fm.append("terms:")
            for t in node_terms[nid]:
                fm.append(f"  - name: {yaml_str(t['name'])}")
                fm.append(f"    tid: {t['tid']}")
        if nid in views:
            fm.append(f"views: {views[nid]}")
        if nid in forum_tid:
            fm.append(f"forum_tid: {forum_tid[nid]}")
        cs = by_node.get(nid, [])
        fm.append(f"comment_count: {len(cs)}")
        if fmt == PHP_FORMAT and "<?" in raw:
            fm.append("needs_crawl: true")
        if nid in SPECIAL_LAYOUTS:
            fm.append(f"layout: {SPECIAL_LAYOUTS[nid]}")
        fm.append("---")

        outdir = CONTENT / ntype
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{nid}.html").write_text(
            "\n".join(fm) + "\n" + html, encoding="utf-8"
        )
        stats[f"type:{ntype}"] += 1

        if cs:
            (DATA / "comments" / f"{nid}.json").write_text(
                json.dumps(cs, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            stats["comments"] += len(cs)

        if nid in poll_choices:
            ch = sorted(poll_choices[nid], key=lambda c: c["weight"])
            (DATA / "polls" / f"{nid}.json").write_text(
                json.dumps(
                    {
                        "nid": nid,
                        "title": title,
                        "active": poll_active.get(nid),
                        "total_votes": sum(c["votes"] for c in ch),
                        "choices": ch,
                    },
                    indent=1,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stats["polls"] += 1

    (DATA / "needs_crawl.json").write_text(
        json.dumps(needs_crawl, indent=1, ensure_ascii=False), encoding="utf-8"
    )

    # --- report ------------------------------------------------------------
    print(f"\nnodes written:     {stats['rendered'] + stats['php_deferred']}")
    print(f"  rendered:        {stats['rendered']}")
    print(f"  deferred to crawl (PHP): {stats['php_deferred']}")
    print(f"comments written:  {stats['comments']}")
    print(f"polls written:     {stats['polls']}")
    print(f"PII rows scrubbed: {dropped_pii} comments had email/IP stripped")
    print("\nby type:")
    for k in sorted(k for k in stats if k.startswith("type:")):
        print(f"  {k[5:]:<14} {stats[k]}")


if __name__ == "__main__":
    sys.exit(main())
