#!/usr/bin/env bash
# Regenerate content/ and data/ from the database dump, in order.
#
# extract.py wipes and rewrites content/, so the two post-processing passes must
# always follow it. Running them out of order silently leaves absolute links and
# dead smiley images in the output.
set -euo pipefail
cd "$(dirname "$0")"

# Wipe first: extract.py only writes, so without this a node removed from the
# corpus (e.g. via EXCLUDED_NODES) would linger in content/ forever.
rm -rf ../content ../data

echo "== 1/6 extract nodes from dump =="
python3 extract.py

echo
echo "== 2/6 generate forum + taxonomy listings =="
python3 extract_structure.py

echo
echo "== 3/6 rewrite inline references =="
python3 rewrite.py --apply

echo
echo "== 4/6 convert dead .wmv links to inline players =="
python3 rewrite_videos.py --apply

echo
echo "== 5/6 scrub personal email addresses =="
python3 scrub_pii.py --apply

echo
echo "== 6/6 replace dead smileys with emoji =="
python3 smileys.py --apply

echo
echo "content/ and data/ regenerated."
