#!/usr/bin/env python3
"""Phase 0 inventory: what is actually in the dump."""
import datetime as dt
from collections import Counter
from pathlib import Path

from dumpq import read_table

DB = Path(__file__).resolve().parent.parent / "legacy" / "db"


def t(name, limit=None):
    p = DB / f"burnoutaholics_com_{name}.sql"
    if not p.exists():
        return [], []
    return read_table(p, limit=limit)


def col(cols, rows, name):
    i = cols.index(name)
    return [r[i] for r in rows if len(r) > i]


def ts(v):
    try:
        return dt.datetime.utcfromtimestamp(int(v)).strftime("%Y-%m-%d")
    except Exception:
        return "?"


def section(title):
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")


# ---------------------------------------------------------------- nodes
section("NODES")
cols, rows = t("node")
print(f"total nodes: {len(rows)}")
types = col(cols, rows, "type")
status = col(cols, rows, "status")
print("\nby type / status (1=published, 0=unpublished):")
combo = Counter(zip(types, status))
for ty in sorted(set(types)):
    pub = combo.get((ty, "1"), 0)
    unpub = combo.get((ty, "0"), 0)
    print(f"  {ty:<16} published {pub:>5}   unpublished {unpub:>5}")
print(f"\ntotal published:   {status.count('1')}")
print(f"total unpublished: {status.count('0')}")

created = [int(x) for x in col(cols, rows, "created") if x and x.isdigit()]
print(f"date range: {ts(min(created))} → {ts(max(created))}")
nids = [int(x) for x in col(cols, rows, "nid")]
print(f"nid range:  {min(nids)} → {max(nids)}  (gaps: {max(nids) - len(nids)} missing ids)")

# non-ASCII in titles: latin1 column, so encoding damage shows up here
titles = col(cols, rows, "title")
odd = [x for x in titles if any(ord(c) > 127 for c in x)]
print(f"\ntitles containing non-ASCII: {len(odd)}")
for x in odd[:8]:
    print(f"   {x!r}")

# ---------------------------------------------------------------- comments
section("COMMENTS")
cols, rows = t("comment")
print(f"total comments: {len(rows)}")
st = col(cols, rows, "status")
print(f"  published (1):   {st.count('1')}")
print(f"  unapproved (0):  {st.count('0')}   <- moderation queue / spam")
mails = [m for m in col(cols, rows, "mail") if m]
hosts = [h for h in col(cols, rows, "hostname") if h]
print(f"  rows carrying an email address: {len(mails)}")
print(f"  rows carrying an IP address:    {len(hosts)}")

# ---------------------------------------------------------------- users
section("USERS")
cols, rows = t("users")
print(f"total user rows: {len(rows)}")
st = col(cols, rows, "status")
print(f"  active (1):  {st.count('1')}")
print(f"  blocked (0): {st.count('0')}")
print(f"  with email:  {len([m for m in col(cols, rows, 'mail') if m])}")
print(f"  with pwhash: {len([p for p in col(cols, rows, 'pass') if p])}")

# ---------------------------------------------------------------- taxonomy
section("TAXONOMY")
vcols, vrows = t("taxonomy_vocabulary")
print(f"vocabularies: {len(vrows)}")
if vrows:
    for r in vrows:
        d = dict(zip(vcols, r))
        print(f"  vid={d.get('vid'):<4} {d.get('name')}")
tcols, trows = t("taxonomy_term_data")
print(f"terms: {len(trows)}")
icols, irows = t("taxonomy_index")
print(f"term→node assignments: {len(irows)}")

# ---------------------------------------------------------------- forum
section("FORUM")
fcols, frows = t("forum")
print(f"forum_index rows (topics): {len(t('forum_index')[1])}")
print(f"forum table rows (topic→forum map): {len(frows)}")

# ---------------------------------------------------------------- urls
section("URL ALIASES")
acols, arows = t("url_alias")
print(f"url_alias rows: {len(arows)}  (expected ~0 — content lives at /node/N)")
for r in arows[:10]:
    d = dict(zip(acols, r))
    print(f"  {d.get('source')} → {d.get('alias')}")

# ---------------------------------------------------------------- files
section("FILES")
fcols, frows = t("file_managed")
print(f"file_managed rows: {len(frows)}")
if frows:
    sizes = [int(x) for x in col(fcols, frows, "filesize") if x and x.isdigit()]
    print(f"total bytes referenced: {sum(sizes):,} ({sum(sizes) / 1e6:.1f} MB)")
    uris = col(fcols, frows, "uri")
    print("uri scheme breakdown:")
    for k, v in Counter(u.split("://")[0] for u in uris if u).most_common():
        print(f"  {k:<12} {v}")

# ---------------------------------------------------------------- privacy
section("PRIVACY-SENSITIVE TABLES")
for name, why in [
    ("pm_message", "private messages between members"),
    ("pm_index", "private message routing"),
    ("watchdog", "system log, contains IPs"),
    ("accesslog", "per-visit log, contains IPs + user agents"),
    ("sessions", "live session tokens"),
    ("profile_value", "user profile fields"),
    ("users", "emails + password hashes"),
]:
    p = DB / f"burnoutaholics_com_{name}.sql"
    if p.exists():
        n = len(read_table(p)[1])
        print(f"  {name:<16} {n:>8} rows   — {why}")

# ---------------------------------------------------------------- polls
section("POLLS")
print(f"polls: {len(t('poll')[1])}")
print(f"poll choices: {len(t('poll_choice')[1])}")
print(f"poll votes: {len(t('poll_vote')[1])}")
