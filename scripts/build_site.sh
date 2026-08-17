#!/usr/bin/env bash
# Full build: content → static assets → Hugo → search index.
#
# Pagefind must run *after* Hugo, because it indexes the rendered HTML in
# public/. Running Hugo alone leaves /search/ working but returning nothing.
set -euo pipefail
cd "$(dirname "$0")/.."

HUGO="${HUGO:-$HOME/.local/bin/hugo}"

echo "== 1/4 regenerate content from the dump =="
./scripts/build_content.sh

echo
echo "== 2/4 assemble theme + legacy assets =="
python3 scripts/theme_assets.py
python3 scripts/collect_assets.py --apply
# _redirects must be committed: Netlify runs only hugo + pagefind.
python3 scripts/gen_redirects.py

echo
echo "== 3/4 hugo build =="
rm -rf public
# Deliberately not --minify: the brief is to match the old site's rendering, and
# HTML minification collapses whitespace, which can shift spacing between inline
# elements. The saving is small; the risk is invisible until someone spots it.
"$HUGO" --gc

echo
echo "== 4/4 pagefind search index =="
npx --yes pagefind@latest --site public --output-subdir pagefind

echo
echo "build complete: $(find public -name '*.html' | wc -l) html files, $(du -sh public | cut -f1)"
