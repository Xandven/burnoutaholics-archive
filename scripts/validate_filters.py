#!/usr/bin/env python3
"""
Fidelity check: does our filter port reproduce what Drupal actually renders?

Fetches a sample of live pages, extracts the rendered body, and diffs it
against the locally-rendered body from the database. Any systematic mismatch
here means Phase 2 output would silently differ from the current site.

Usage:  python3 validate_filters.py [sample_size]
"""
import difflib
import re
import subprocess
import sys
import time

from drupal_filters import render, repair_mojibake
from dumpq import read_table

DB = "../legacy/db/burnoutaholics_com_"
DELAY = 1.5  # be kind to the old server

_TAG = re.compile(r"<(/?)div\b[^>]*>", re.I)
_MARKER = '<div class="field-item even" property="content:encoded">'


def extract_body(html):
    """Pull the rendered body out of a Drupal page by balancing <div>s."""
    i = html.find(_MARKER)
    if i < 0:
        return None
    start = i + len(_MARKER)
    depth = 1
    for m in _TAG.finditer(html, start):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return html[start:m.start()]
    return None


def normalise(s):
    """Ignore differences that cannot affect rendering."""
    if s is None:
        return ""
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r">\s+<", "><", s)
    return s.strip()


def fetch(nid):
    try:
        out = subprocess.run(
            ["curl", "-sS", "-L", "--max-time", "25",
             f"https://burnoutaholics.com/node/{nid}"],
            capture_output=True, timeout=40,
        )
        return out.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""


def main():
    n_sample = int(sys.argv[1]) if len(sys.argv) > 1 else 20

    bc, br = read_table(DB + "field_data_body.sql")
    nc, nr = read_table(DB + "node.sql")
    bi = {n: k for k, n in enumerate(bc)}
    ni = {n: k for k, n in enumerate(nc)}

    status = {r[ni["nid"]]: r[ni["status"]] for r in nr}
    titles = {r[ni["nid"]]: r[ni["title"]] for r in nr}

    # Only published, non-PHP nodes can be compared against the live site.
    cands = [
        r for r in br
        if r[bi["body_format"]] in ("1", "3")
        and status.get(r[bi["entity_id"]]) == "1"
        and (r[bi["body_value"]] or "").strip()
    ]
    # Spread the sample across the whole corpus rather than clustering.
    step = max(1, len(cands) // n_sample)
    sample = cands[::step][:n_sample]

    print(f"comparing {len(sample)} nodes against the live site\n")
    exact = close = bad = missing = 0
    failures = []

    for r in sample:
        nid = r[bi["entity_id"]]
        fmt = r[bi["body_format"]]
        local = normalise(render(repair_mojibake(r[bi["body_value"]]), fmt))

        page = fetch(nid)
        time.sleep(DELAY)
        live = extract_body(page)
        if live is None:
            missing += 1
            print(f"  node/{nid:<5} fmt{fmt}  -- no body found on live page")
            continue
        live = normalise(repair_mojibake(live))

        if local == live:
            exact += 1
            mark = "EXACT"
        else:
            ratio = difflib.SequenceMatcher(None, local, live).ratio()
            if ratio > 0.98:
                close += 1
                mark = f"close {ratio:.4f}"
            else:
                bad += 1
                mark = f"DIFF  {ratio:.4f}"
                failures.append((nid, fmt, local, live))
        print(f"  node/{nid:<5} fmt{fmt}  {mark:<14} {titles.get(nid,'')[:40]}")

    total = exact + close + bad
    print(f"\n{'=' * 58}")
    print(f"exact: {exact}/{total}   close(>0.98): {close}   differing: {bad}")
    if missing:
        print(f"pages with no extractable body: {missing}")

    for nid, fmt, local, live in failures[:3]:
        print(f"\n--- node/{nid} (format {fmt}) first differences ---")
        for line in list(difflib.unified_diff(
            [local[i:i + 90] for i in range(0, min(len(local), 900), 90)],
            [live[i:i + 90] for i in range(0, min(len(live), 900), 90)],
            "local", "live", lineterm="", n=1,
        ))[:16]:
            print("  " + line)


if __name__ == "__main__":
    main()
