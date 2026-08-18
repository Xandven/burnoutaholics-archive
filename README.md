# burnoutaholics.com — static archive

Tooling and source for turning [BurnoutAholics.com](https://burnoutaholics.com) — a Burnout
fan community that ran on Drupal 7 from 2007 to 2024 — into a static site that can be hosted
for the cost of nothing and kept online indefinitely.

The goal is preservation, not reinvention. The archive looks like the site it replaces: same
Bartik theme, same fonts and colours, same logo, same 960px layout, and the same URLs. What
changes is that nothing needs a database, a PHP runtime, or a security patch ever again.

**Status:** the archive builds and is deployable — content, theme, search, video
transcoding, redirects and Netlify configuration are all in place. Final QA and the DNS
cutover are outstanding. See [`PLAN.md`](PLAN.md), the working plan of record, which is
considerably more detailed than this file and records why things are the way they are.

## What's here

| | |
|---|---|
| **2,072** posts | blog, news, forum topics, FAQs, game guides, polls |
| **7,218** comments | rendered inline, frozen, personal data removed |
| **434** forum topics | across 6 forums, with original topic/post counts |
| **54** taxonomy terms | at their original `/taxonomy/term/<tid>` paths |
| **2,655** built pages | from a ~55s Hugo build |

Written by roughly 500 people between 2007 and 2024.

## How it works

The site is rebuilt from a MySQL dump rather than scraped, so the content stays editable
rather than frozen as rendered HTML. Three things make that work:

**Drupal's text filters are reimplemented, not approximated.** `scripts/drupal_filters.py`
is a port of the four filters this site used (`filter_url`, `filter_html`, `filter_autop`,
`filter_htmlcorrector`), chained in Drupal's configured order. Output is diffed against the
live site page by page: **38/40 byte-exact** on the filter port, and **617 exact / 6
differing out of 654** on full page bodies once deliberate changes are normalised out.

**The theme is copied, not rewritten.** Bartik's stylesheets are lifted verbatim out of the
Drupal tree to their original URL paths, and the page chrome (menus, sidebar blocks, footer)
is extracted from crawled pages rather than retyped, so it cannot drift.

**A crawl of the live site is kept as ground truth.** 3,090 URLs, used both to verify
rendering and to recover the handful of pages whose bodies were executable PHP.

Several things are deliberately *not* faithful, because the original was broken:

- Legacy `?q=path` URLs resolved to the front page; they now go where they say.
- 4,183 smiley images had 404'd for years (the module was removed); they are now emoji.
- Site search timed out after 20s; it is now a static [Pagefind](https://pagefind.app) index.
- The gamertag generator hadn't executed in years; it is reimplemented in JavaScript.

## Layout

```
content/        generated — one HTML file per node, YAML frontmatter
data/           generated — comments, polls, forum and taxonomy listings as JSON
layouts/        Hugo templates, incl. chrome partials extracted from the live site
static/         Bartik CSS, Drupal core assets, and the site's own /files tree
scripts/        extraction, rewriting, crawling and verification tooling
PLAN.md         the plan of record — decisions, findings and what's left
```

`content/` and `data/` are **generated**. Edit the scripts, not the output.

Not in this repository: the MySQL dump, the Drupal source tree, and the crawl. They are
large, and the dump contains user email addresses, password hashes and private messages.

## Building

Requires [Hugo](https://gohugo.io) (extended), Python 3.9+, and Node (for Pagefind). No
MySQL server is needed — `scripts/dumpq.py` reads mysqldump files directly.

```bash
./scripts/build_site.sh      # content → assets → hugo → search index
```

To rebuild only the content from the dump (requires `legacy/`):

```bash
./scripts/build_content.sh   # extract → listings → rewrite links → video players
                             # → scrub personal data → emoji
```

Order matters and the script enforces it; running the steps by hand in the wrong order
fails silently. `content/` and `data/` are wiped and regenerated each run, so a manual
edit there will not survive — change the scripts instead.

## Deploying

Netlify builds from the committed `content/` and `data/`; it does **not** regenerate them
from the dump, because `legacy/` never leaves the maintainer's machine. The deploy is only
the last two steps of the local build:

```
hugo --gc  →  pagefind --site public
```

`netlify.toml` pins the Hugo and Node versions, sets caching headers, and holds the
redirects that keep old URLs alive: `/node` → `/`, 410s for account and posting routes, and
— generated into `static/_redirects` by `scripts/gen_redirects.py` — one rule per clip
mapping the old `.wmv` URLs onto the transcoded MP4s.

If you change anything under `scripts/`, rebuild locally and commit the regenerated
`content/`, `data/` and `static/_redirects`. Netlify will not do it for you.

### Verification tooling

These are the reason the archive can be trusted, and they are worth running after changes:

```bash
python3 scripts/validate_filters.py 40   # diff rendered bodies against the live site
python3 scripts/check_links.py           # internal link check over public/
python3 scripts/check_assets.py          # every referenced asset resolves
python3 scripts/inventory.py             # what is actually in the dump
```

Current state: **7 broken internal links out of 160,895**, and all 5 remaining targets were
already broken in the original content.

## Licence

Three kinds of material live here, under three different terms.

**Code written for this project** — `scripts/` and `layouts/`, with the two exceptions
below — is [MIT](LICENSE). The mysqldump reader, the extractors and the verification
tooling are reusable for any Drupal-to-static migration.

**Drupal-derived code and assets** are **GPL-2.0-or-later**, because Drupal is:

- `static/themes/bartik/`, `static/modules/`, `static/sites/`, `static/misc/` — core CSS
  and images, copied verbatim for fidelity (39 files, ~104 KB).
- `layouts/partials/drupal/*.html` — chrome markup extracted from Drupal's rendered output.
- `scripts/drupal_filters.py` — a port of Drupal 7's text filters. `_filter_autop()` is a
  direct translation of the original, quirks preserved deliberately, and a translation is a
  derivative work. Calling it MIT would be wrong.

No Drupal PHP, modules or executable code are present — the archive needs none.

**Site content** — `content/`, `data/`, `static/files/` — is
[CC BY-SA 4.0](CONTENT-LICENCE.md) so far as the site's creator can grant it: credit
required, and derivatives stay equally open.

That last grant has a real limit worth stating plainly. Around **500 people** wrote the
posts and comments in this archive. Copyright in their words is theirs, not the site
owner's, and no site can license away contributors' rights retroactively. Their work is
published here as a community archive on the same terms it was originally posted under.

Email addresses, IP addresses, password hashes and the site's 3,608 private messages are
**not** published — they are dropped during extraction, not filtered afterwards. If you
wrote something here and want it removed, see
[removal requests](CONTENT-LICENCE.md#removal-requests).

## Credit

BurnoutAholics.com was created and run by **Kristian Sandven** ("Xandu"), with
ZombieTron and the BurnoutAholics community, 2005–2024. Burnout is a trademark of Electronic Arts; this is an unaffiliated
fan archive.
