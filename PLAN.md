# burnoutaholics.com — Drupal 7 → static site

Plan of record. Written 2026-08-15, before source material landed in the repo.

## 1. Current state (verified against the live site)

| Thing | Finding |
|---|---|
| Platform | Drupal 7, PHP 8.2.30, nginx 1.28.0 |
| Theme | Bartik, recoloured (`/files/color/bartik-c329b437/colors.css`) |
| Front page | `/node` (default node listing); `/` 301s to it. Pager at `?page=N` |
| Content URLs | **`/node/N` — no path aliases.** `<link rel="canonical">` on `/node/1219` is `/node/1219`, so pathauto is not in play |
| Node ID range | Up to ~3645 (`/node/3700` is 404), with gaps |
| Forums | 6 forums under 2 containers, ~**2,275 posts** total (`/forum/22` alone has 1,740) |
| Taxonomy | `/taxonomy/term/N` and `/taxonomy/term/N/all` and `/taxonomy/term/N/M` all in use |
| Files | Served from **`/files/...`**, not the Drupal default `/sites/default/files` (which 404s) |
| Modules in evidence | aggregator, comment, poll, forum, views, ctools, search, adsense |
| Sitemap | **None** — `/sitemap.xml` returns the 404 page |
| robots.txt | Present, `Crawl-delay: 10` |
| Last content | Sep 2024 (`/node/3645` "BurnoutAholics.com is back online!") |
| Site age | 19+ years of community content |

### Two findings that shape the plan

**Legacy `?q=` URLs are already broken.** The site's own navigation still links to
`http://burnoutaholics.com/?q=taxonomy/term/13/all` (the "Dominator" nav item). That URL
today resolves to `/node` — the front page — not the taxonomy listing. So this is an
existing bug, not something we must faithfully reproduce. The static build can *fix* it by
mapping `?q=<path>` → `/<path>`. Worth doing: there are 20 years of inbound links in that
format from forums and old blogs.

**Drupal's search is effectively dead.** `/search/node/burnout` did not respond within 20
seconds. Database-backed search on this content volume is a real performance liability and
is one of the things static hosting straightforwardly improves.

### Phase 0 inventory results (measured from the dump, 2026-08-15)

Dump is **complete**: 249 per-table files, all content tables present. Source was Azure
MySQL 5.7, dumped with mysqldump 8.0.29. Parsed with `scripts/dumpq.py` (no MySQL server
needed — the dumps are read directly).

**The site is far smaller than its node IDs suggest: 2,073 nodes, not 3,646.**
1,573 IDs are gaps from deleted content.

| Content type | Published | Unpublished |
|---|---:|---:|
| blog | 1,129 | 13 |
| forum | 437 | 2 |
| story | 235 | 8 |
| poll | 104 | 1 |
| faq | 81 | 0 |
| page | 19 | 7 |
| gameguide | 14 | 1 |
| clip | 12 | 0 |
| event | 6 | 0 |
| chat / tournament / webform | 3 | 1 |
| **Total** | **2,040** | **33** |

- **Comments**: 7,245 — of which only **27** are unapproved. The spam backlog is trivial.
- **Users**: 1,573 (1,571 active), all with email + password hash.
- **Taxonomy**: 9 vocabularies, 54 terms, 1,132 term→node assignments.
- **Forum**: 434 topics; the ~2,275 "posts" seen on the live site = topics + replies.
- **Polls**: 105 polls, 510 choices, 14,279 votes.
- **`url_alias`: 0 rows** — confirms content lives at `/node/N` with no aliases.
- **Content dates**: 2007-04-30 → 2024-09-01. Nothing pre-2007 survives in the database,
  though the site predates that; earlier content was presumably lost in an old migration.

**Encoding damage is real but bounded.** `node` and `comment` are `latin1_general_ci` while
the body tables are `utf8`. 11 node titles contain non-ASCII, of which **8 are
double-encoded** (`Xanduâ€™s Demo experience`) and **3 are already correct**
(`Building a new PC – PART 1`). A blanket repair would corrupt the correct ones. Verified
fix: apply `cp1252 → utf-8` round-trip *only* to strings matching a mojibake signature
(`Ã.`, `â€.`, `Â.`) and *only* when the result no longer matches it — 8 repaired, 3 left
untouched, 0 broken. Same treatment needed for comment subjects and body text.

**`file_managed` is not the asset inventory.** It lists only 353 files totalling 1.7 MB —
almost all user avatars — while `legacy/files/` is **92 MB**. The bulk (e.g.
`burnoutparadise/` 45 MB, `dominator/` 11 MB, `users/` 9.5 MB) is referenced directly from
post HTML and is invisible to Drupal's file tables. **Asset migration must copy the whole
`/files` tree and resolve references by scanning body HTML, not by reading `file_managed`.**
Note also that `file_managed.uri` holds plain relative paths (`files/pictures/…`), not the
Drupal-standard `public://` scheme — consistent with the non-standard `/files` root.

**The gamertag generator is already broken in production.** `legacy/drupal/NameGen/BurnoutNames.php`
is a pre-Drupal relic from 2006–07 that relies on `register_globals` (`$REQUEST_METHOD`,
`$realname`), removed in PHP 5.4. The live site runs PHP 8.2, and a POST to it returns the
form with no result. Its logic is trivial: a deterministic seed
(`Σ ord(name[i]) × (i+1)`), then `srand`/`rand` picking from a 67-word adjective list and a
43-word noun list to make "*My name is **Bitter Takedown** and I am a BurnoutAholic.*"
Reimplementing it client-side would **restore** a feature, not preserve one.

**Privacy-sensitive tables that must never reach the build:** `pm_message` (3,608 private
messages between members), `pm_index` (6,310), `accesslog` (80,103 rows with IPs and user
agents), `watchdog` (1,440), `profile_value` (14,291), and `users` (1,573 emails +
hashes). Every one of the 7,245 comments carries an IP address and 349 carry an email —
these columns get dropped at extraction, not filtered later.

**Discardable bulk**: `cache_page` alone is 997 MB of the 1.2 GB `db/` directory. With
cache, log, search-index and voting tables excluded, the real content is a few MB.

## 2. Decisions locked

- **Community content**: frozen as a read-only archive. Forum threads, comments and polls
  stay readable and indexable; no new posts, no logins, no registration.
- **Approach**: hybrid. Articles/news/pages are regenerated from the MySQL dump into clean
  Markdown and rebuilt in a static generator. The forum archive comes from a crawl of the
  rendered site rather than from the database.
- **Hosting**: Netlify. Free
  tier, automatic HTTPS, CDN, and `_redirects` support, which we need.
- **Repo**: stays local. Raw dump, Drupal source and `/files` are gitignored anyway — they
  are large and carry personal data, and keeping them out of history preserves the option
  of pushing this somewhere later.
- **Visual fidelity**: the new site must look like the old one — same fonts, colours, logo
  and layout. Desktop is pixel-identical; mobile breakpoints are added below 960px only.
  See the design spec below.

### Why the forum is crawled and not migrated

Forum threads are the highest-volume, lowest-edit-value content on the site. Rebuilding
them from `forum`/`forum_index`/`comment` tables means reimplementing thread paging, reply
nesting and user attribution for content nobody will ever edit again. Crawling gives a
faithful archive for a fraction of the effort. The database extraction effort is better
spent on the ~hundreds of articles and news posts that are the site's actual legacy.

### Design spec (captured from the live theme)

Theme is Bartik with the custom colour scheme `bartik-c329b437`.

| Token | Value |
|---|---|
| Body / slogan font | `Georgia, "Times New Roman", Times, serif` |
| Header, site name, menus | `"Lucida Grande", "Lucida Sans Unicode", Verdana, sans-serif` |
| Alternate UI font | `"Helvetica Neue", Helvetica, Arial, sans-serif` |
| Monospace | `Menlo, Consolas, "Andale Mono", "Lucida Console", …` |
| Base type | `font-size: 87.5%`, `line-height: 1.5` |
| Body text | `#3b3b3b` |
| Content background (`#page`, `#main-wrapper`) | `#ffffff` |
| Header bar (`#header`) | `#333` |
| Outer frame (`#page-wrapper`, `#footer-wrapper`) | `#1f1d1c` |
| Links | `#d61111`; hover/focus `#ff0f0f`; active `#ff4545` |
| Sidebar blocks | background `#eee`, border `#ededed` |
| Header / site-name text | `#fffeff` |
| Logo | `/files/NewBALogo.png` — 463×163 RGBA PNG, 32 KB |
| Grid | fixed **960px** centred; `#page-wrapper` has `min-width: 960px` |
| Columns | `.one-sidebar`: `#content` 720px + `#sidebar-first` 240px; section padding `0 15px` |

**No webfonts.** Every stack is system fonts, so rendering is identical to today with
nothing to license, self-host or preload. (Lucida Grande resolves on macOS and falls back to
Lucida Sans Unicode / Verdana elsewhere — already true on the live site.)

**DOM structure to reproduce:**

```
#page-wrapper > #page
  #header            → logo, #name-and-slogan (h1#site-name, #site-slogan),
                       .region-header (search block)
  #main-menu
  #main-wrapper > #main
    #sidebar-first   → menu-community, menu-features, system-main-menu,
                       poll-recent, [user-login → replaced]
    #content         → #highlighted, #block-system-main
  #footer-wrapper
```

**Consequence for implementation:** because fidelity is the requirement, the theme is
*ported, not rewritten*. Bartik's `layout.css`, `style.css` and the generated `colors.css`
are copied out of the Drupal source and served as-is, and the Hugo templates emit Bartik's
class and ID structure. This is both more faithful and less work than authoring new CSS.

## 3. Proposed layout

```
legacy/            # gitignored, on-disk working material
  drupal/          #   Drupal 7 source tree
  files/           #   the /files asset tree
  db/              #   *.sql dumps
mirror/            # gitignored, regenerable — raw wget crawl output
content/           # tracked — extracted Markdown + frontmatter
site/              # tracked — Hugo project (templates, assets, config)
static/forum/      # tracked — cleaned frozen forum archive
scripts/           # tracked — extraction, cleanup and build tooling
```

## 4. Phases

### Phase 0 — Safety and inventory 

The dump is the irreplaceable artefact; everything else can be redone.

- [x] Land `legacy/db/*.sql`, `legacy/drupal/`, `legacy/files/` on disk.
- [x] Take a second copy of the dump somewhere off this machine (encrypted). If the old
      host dies mid-project, this is the only copy of the unpublished content.
- [x] Confirm the dump is complete: does it include `comment`, `field_data_body`,
      `taxonomy_*`, `file_managed`, `forum*`, `poll*`, `users`? A structure-only or
      partial dump is a common and expensive surprise.
- [x] ~~Load the dump into a local MySQL/MariaDB~~ — **not needed.** No MySQL or Docker on
      this machine, and the per-table dumps are clean enough to read directly.
      `scripts/dumpq.py` parses mysqldump extended-INSERT syntax (quoting, backslash
      escapes, NULLs) into rows. Faster to run and reproducible without a server.
- [x] Inventory queries — see "Phase 0 inventory results" in §1. All key numbers captured
      via `scripts/inventory.py`.

### Phase 1 — Capture while Drupal is still running

**Time-critical.** Everything here is impossible once the old host is switched off, so it
happens before any migration work, not after.

- [x] **Crawl is DB-driven, not recursive** (`scripts/crawl.py`). The URL list is built from
      the database — every published node, every forum and taxonomy listing, every pager —
      so coverage is provable. Link-following would silently miss anything unlinked.
      Resumable via `mirror/manifest.json`; re-running skips what it already has.
- [x] **Crawl complete.** 3,090 URLs over ~2h at ~21/min: **3,076 OK**, 12 not found (the
      nginx-blocked PHP nodes), 2 forbidden (unpublished). Covers all 2,040 node pages, the
      forum and taxonomy listings, and every pager. Mirror is ~99 MB.
- [x] **Zero unrecovered failures.** 39 URLs failed with connection timeouts during the main
      pass (the old server struggles under sustained load). Re-running `crawl.py all`
      retried exactly those 39 and recovered all of them — the resume logic deliberately
      treats `000` as "retry", not "done", so transient failures cannot be baked in as
      permanent gaps.
- [x] `/files/` does **not** need crawling — `legacy/files/` (92 MB) is already a complete
      copy of the asset tree.
- [x] **Pre-Drupal assets collected** (`scripts/collect_assets.py`). The site predates
      Drupal and old posts still link to the original static directories. 25 files (31.9 MB)
      copied into `static/`: 13 `/videos/*.wmv` and 12 `/Images/*`. Only *referenced* files
      are copied — `/videos` holds 471 MB across 37 files, but just 13 are linked from any
      post, so mounting the directory wholesale would have put 439 MB of orphaned originals
      into every deploy.
- [x] **Asset audit** (`scripts/check_assets.py`): of 304 distinct referenced asset paths,
      298 now resolve. The 6 that do not were already broken in the original content —
      e.g. a link to `…/sj/jump7` where the file on disk is `jump7.jpg`, and `/bo_paradise`
      where the file is `/files/bo_paradise.jpg`. These belong in the Phase 6 dead-link
      report, not in a rewrite rule.
- [x] Crawl as an anonymous visitor, deliberately. The archive should contain exactly what
      the public could already see, which sidesteps a whole class of privacy problems.
- [x] Record a manifest (URL → HTTP status → bytes) as the baseline for Phase 6 QA.

### Phase 2 — Extract content from the database

**Status: core extraction complete.** `scripts/extract.py` produces
`content/<type>/<nid>.html` (2,073 files), `data/comments/<nid>.json` (1,472 files,
7,218 comments) and `data/polls/<nid>.json` (105 files).

**Output is HTML, not Markdown.** The original plan said Markdown, but exact visual
fidelity became a hard requirement, and an HTML→Markdown→HTML round trip loses tables,
`<font>`, inline markup and Flash/video embeds. Hugo passes `.html` content files through
untouched, so bodies are stored as rendered HTML with YAML frontmatter. Frontmatter carries
`url: /node/N`, which is what preserves the URL scheme (§5) directly.

- [x] Export nodes with frontmatter (title, nid, type, created, changed, author, terms,
      status, view count, comment count). Body from `field_data_body`.
- [x] Handle input formats correctly. `scripts/drupal_filters.py` is a port of the four
      Drupal 7 filters this site uses, chained in the configured weight order:
      - format 1 "Filtered HTML" (1,810 nodes): url → html → autop → htmlcorrector
      - format 3 "Full HTML" (140 nodes): url → autop → htmlcorrector
      - format 2 "PHP code" (17 nodes): executable — see below
- [x] **Validated against the live site**: `scripts/validate_filters.py` fetches live pages,
      extracts the rendered body and diffs it against locally-rendered output.
      **38/40 byte-exact**, 1 close (>0.99), 1 differing only in `xml:lang` attributes.
      Getting there required four fidelity fixes, each confirmed against a real page:
      1. `filter_url` must linkify in a **single pass** — matching URLs, `www.` and emails
         in sequence re-scans markup the previous pass created, producing nested
         `<a href="http://<a href=…">` garbage (node/114).
      2. `filter_htmlcorrector` must **decode HTML entities** to characters, as Drupal's
         `DOMDocument` load/serialise pair does — `&hellip;` → `…` (node/653).
      3. It must also apply **implied end tags** (`<p>` closed by a following block element,
         `<li>` by `<li>`, …), or `<p>a<p>b` nests instead of becoming siblings (node/1066).
      4. Bodies must be **CRLF-normalised to LF** before filtering. Stored bodies use CRLF
         from HTTP form submission; autop's `(?<!<br />)\s*\n` rule otherwise fires on the
         `\n` after a `\r` and emits a doubled `<br />` (node/1684 — exact only with this).
      Also: Drupal's `filter_xss` strips `style` attributes but keeps others such as `size`
      on `<font>`; and `<embed>` is **not** a void element (old Flash markup nests it inside
      `<object>` and closes it explicitly).
- [x] **Repair mojibake selectively** using the verified cp1252 rule.
- [x] **Drop personal-data columns at extraction.** `comment.mail` and `comment.hostname`
      are discarded for all 7,218 comments; only `users.name` is carried across. Verified by
      sweeping the output — no email or IP reaches `content/` or `data/` from any DB column.
- [ ] Sanitise 20 years of hand-written HTML: unclosed tags, `<font>`, inline styles,
      tables used for layout, MySpace-era markup. Run through a real HTML parser and
      normalise; do not regex it.
- [x] Render comments into structured JSON per node, **usernames only**, unapproved
      excluded (27 rows).
- [x] Freeze polls: 105 poll result sets written with final vote tallies.
- [x] **16 PHP-bodied nodes resolved via the crawl** (`data/needs_crawl.json`). Result:
      - **6 render and were captured**: /node/4, /10, /295, /775, /2020, /2635
      - **8 return a bare nginx 404** — /node/172, /897, /898, /899, /900, /901, /2019,
        /2033. The 404 comes from nginx, not Drupal, and neighbouring node IDs serve fine,
        so these URLs were deliberately blocked at the web server — almost certainly because
        Drupal 7's PHP filter is a known RCE risk. **They are already invisible to the
        public**, so omitting them from the static site changes nothing for visitors.
      - **2 return 403**: /node/1218, /node/2021 — both unpublished, so excluded regardless.
      `/node/1219` (Burnout Paradise, a main-nav page) was tagged format 2 but contains no
      PHP, so it renders normally and was never in this list.
- [x] Rewrite inline references (`scripts/rewrite.py`, applied). Operates on `href`/`src`
      values only, never free text; JSON comment files are re-serialised structurally.
      319 files changed: **542** absolute self-links made root-relative, **333** `?q=` links
      repaired, **48** dead links (`/user/*`, `/comment/reply/*`, `/node/add/*`, node 2120)
      unwrapped to plain text so sentences still read. Verified afterwards: 0 absolute
      self-links remain and all 1,472 comment files still parse as JSON. Ten `?q=` strings
      are left deliberately — six are external Google thumbnail URLs and four are malformed
      in the original source (`http:///?q=node/11`).
- [x] **`/node/2120` removed.** Excluded in `extract.py` via `EXCLUDED_NODES`, so the
      decision is reproducible rather than a manual deletion. Post-removal sweep: real IP
      addresses in the output dropped to **0**, embedded emails from 155 to 69 (the
      remainder are ordinary contact addresses in news posts, e.g. `backcomp@microsoft.com`).
- [ ] Rewrite inline references: `/files/...` asset paths, `/node/N` cross-links, and
      absolute `http://burnoutaholics.com/...` links (including the broken `?q=` form).
- [ ] Render comments into the page they belong to, as static markup, with **usernames
      only** — commenter emails, IPs and hostnames must not reach the output.
- [ ] Decide per content type what carries over. Expect `blog`, `story`/`article`, `page`,
      `poll`, `forum`. Aggregator feed items are almost certainly dead external content and
      probably should not be republished.
- [x] Freeze polls: render the final vote tallies as a static result table.

### Phase 3 — Build the static site

**Status: skeleton building.** `hugo.toml` + `layouts/` produce **2,141 pages** (2,039 at
`/node/N`, plus listings, 300 paginator pages, 50 aliases) from a clean build.
Hugo v0.148.2 extended is installed as a **user-local binary** at `~/.local/bin/hugo` —
no sudo, nothing system-wide.

**Verified against the live site.** Comparing every crawled page's rendered body with the
built page, and normalising out the changes we made deliberately (emoji, dead-link
unwrapping, URL rewriting): **617 exact, 31 close (>0.98), 6 differing of 654**. The six are
edge cases in malformed 2007 markup (an unterminated `<script>` inside a comment,
apostrophe escaping in an attribute) plus artifacts of the comparison script.

That comparison caught two real bugs in our own rewriter, both invisible without it:
`?q=node/10&wmv=X` was being rewritten to `/node/10&wmv=X` (the surviving query string needs
a `?`, not concatenation), and the HTML-entity form `&amp;wmv=` became the nonsense
`?amp;wmv=`.

- [x] Hugo (single binary; builds the full site in ~60s).
- [x] **Ported the Bartik theme rather than rewriting it.** `scripts/theme_assets.py` copies
      all 17 stylesheets verbatim out of `legacy/drupal/` to their original URL paths
      (`/themes/bartik/css/style.css`, `/modules/system/system.base.css`, …), plus Bartik's
      own images. `colors.css` comes free via the `/files` mount.
- [x] **Page chrome lifted from the crawl, not retyped** (`scripts/extract_chrome.py`).
      The main menu, the three sidebar menu blocks, the footer and the triptych region are
      extracted from a crawled page into `layouts/partials/drupal/`, with the same link
      rewriting applied. Retyping menus by hand would introduce drift; this cannot.
      Side effect: the long-broken `?q=taxonomy/term/13/all` "Dominator" nav link now works.
- [x] Logo and favicon stay at their existing paths, served from the `/files` mount.
- [x] Front page reproduces Drupal's rule — `promote=1`, sticky first, then newest, 10 per
      page. Verified: it lists 3645, 3638, 3621, 3607, 3603 in the same order as the live site.
- [x] Mobile breakpoints in `static/css/archive.css`, **below 960px only**. The file is
      loaded last and every rule is inside a `max-width` query or targets archive-only
      markup, so at ≥960px it changes nothing.
- [x] Added the `<meta name="viewport">` tag the original lacks.
- [x] **Forum archive built from the database, not embedded crawl HTML.**
      `scripts/extract_structure.py` emits the forum tree, per-forum topic lists and
      paginated stub pages. Markup mirrors Drupal's `table#forum-0` / `table#forum-topic-N`
      so `forum.css` applies unchanged. **Topic and post counts match the live site exactly**
      for all six forums (331/1740, 94/499, 4/27, 3/3, 1/4, 1/2), and forum ordering
      reproduces Drupal's — sorted by term *weight*, not tid, giving 22, 40, 38, 39, 23, 55.
- [x] **Taxonomy term pages at their original `/taxonomy/term/<tid>` paths.** All 54 terms
      get a page, including the 10 with no content — they are linked from menus, and an
      empty listing beats a 404. Two-segment legacy links (`/taxonomy/term/20/35`) are
      registered as aliases after confirming the live site ignores the trailing segment.
- [x] **`/tracker` (Recent posts)** rebuilt: 2,039 posts ordered by latest activity, using
      `node_comment_statistics.last_comment_timestamp` where present.
- [x] Pagination for data-driven listings is materialised as real stub pages
      (`/forum/22/page/2`), because Hugo only paginates Pages, not data files.
      `layouts/partials/datapager.html` draws Drupal's pager markup.
- [x] Drupal core `/misc` assets (feed icon, pager arrows, message icons) copied.
- [x] ~~Per-game landing pages~~ — the note was stale. The per-game nav items are node
      pages (Paradise `/node/1219`, Revenge `/node/1223`, Takedown `/node/1234`, Point of
      Impact `/node/69`, Burnout `/node/38`) and taxonomy pages (Dominator
      `/taxonomy/term/13/all`, CRASH `/taxonomy/term/36/4`), not sections — all verified
      rendering with the right templates and titles. The generic list template is used only
      by content-type sections, of which just `/blog` and `/poll` are linked from a menu,
      and a teaser list is right for both.
- [x] ~~Integrate the forum archive as pre-built crawl HTML~~ — **superseded.** It is built
      from the database instead (see above): same markup, working pagination, and counts
      that match the live site exactly. Embedding crawled HTML would have frozen the chrome
      of every forum page at crawl time.
- [x] **`/rss.xml`** — served at its original path with a bespoke template
      (`layouts/index.rss.xml`). Matches Drupal's feed: nodes promoted to the front page,
      newest first, **10 items**. Hugo's default would have emitted every page on the site —
      2,472 items and 1.7 MB, which is not a subscribable feed. Per-section feeds are capped
      at 10 via `services.rss.limit`.
- [x] **`sitemap.xml`** — 2,484 URLs, and a `robots.txt` that points at it. The old site
      had neither; its robots.txt was mostly Disallow rules for Drupal paths that no longer
      exist.

### Menu links restored from Wayback captures (2026-08-16)

Four navigation links had stopped working and were rebuilt against archived
captures of the pre-Drupal-7 site.

**The two-segment taxonomy URLs are Drupal 6's AND syntax.** `/taxonomy/term/A/B`
lists nodes carrying *both* terms and takes its title from the first. Drupal 7
dropped that behaviour and serves term A alone, which is why these menu items had
silently degraded. Verified against the captures:

| Link | Menu item | Result | Matches capture |
|---|---|---|---|
| `/taxonomy/term/20/35` | GCA 08 | 4 posts (term 20 ∩ 35) | exactly |
| `/taxonomy/term/36/4` | CRASH! | 7 posts (term 36 ∩ 4) | exactly |
| `/taxonomy/term/13/all` | Dominator | 5 posts | exactly |
| `/taxonomy/term/19/all` | Featured Articles | 7 posts | capture had 6; node 2194 tagged later |

An earlier attempt aliased `/taxonomy/term/20/35` to term 20 ("General"), which
looked plausible because the *live* site does exactly that — but the capture shows
it listing the four GCA posts, which is term 20 ∩ term 35. The title stays
"General" for fidelity; a subheading names both filters so the page is not
confusing.

**`/faq` rebuilt** (`layouts/faq/list.html`) from the 2015 capture: 81 questions in
7 categories, jump-list on top and answers inline below, with the original
`t<tid>n<nid>` anchor names preserved so deep links such as `/faq#t45n51` still
land correctly. Category counts match the capture exactly (2, 1, 2, 2, 36, 30, 8).
Added to the Features menu below the Gamertag Generator, via
`scripts/extract_chrome.py` so it survives re-extraction of the chrome.

**A Hugo trap worth recording:** `term` is a reserved layout name for taxonomy-term
kind. A normal page with `layout: term` silently falls back to `single.html` — every
taxonomy listing was rendering as an empty node page, and both templates emit the
same `<h1>`, so the title looked right. Renamed to `termlist`.

### Phase 4 — Replace the dynamic features 

| Feature | Disposition |
|---|---|
| Smileys | **Replaced with Unicode emoji** (`scripts/smileys.py`, applied). 4,183 dead `<img>` tags across 1,267 files mapped to 92 distinct emoji, zero unmapped. No third-party assets, no licensing question, renders everywhere, cannot break again. The original FCKeditor images were unrecoverable — absent from `legacy/drupal/` and 404 on the live site |
| Site search | **Pagefind — done.** Index built after Hugo by `scripts/build_site.sh`: 2,037 pages, 20,774 words. Only node bodies are indexed (`data-pagefind-body`), with the header, menus, sidebar and footer marked `data-pagefind-ignore` — otherwise every page matches every menu word. The UI bundle loads on `/search/` only, so the other 2,650 pages carry no search JS. The header box hands off via `?q=` |
| Gamertag generator | **Done** — reimplemented client-side (`layouts/_default/gamertag.html`), reading the real 404 × 92 word lists from `/files/bo_first` and `/files/bo_last` (37,168 combinations). Keeps the original seed formula and determinism per name. It does **not** reproduce the 2007 outputs: that depended on the host C library's `rand()`, and there is nothing to verify a replica against — the live page renders the intro but no form at all, so the PHP has not executed in years |
| Contact form | **Dropped** (node 3639). Its body is empty — the form came entirely from the webform module, absent from `legacy/drupal` — so it would have been a blank page titled "Feedback", and `promote=1` would have put it on the front page |
| AdSense | **Removed — all three slots** (2026-08-17, reversing the earlier decision to keep them). The 728x90 header leaderboard, the 160x600 "Support US!" sidebar block and the 200x200 footer block are gone. `strip_ads()` in `scripts/extract_chrome.py` removes any `block--managed-N` div containing AdSense markers, so they cannot reappear when the chrome is re-extracted from the crawl. Whole blocks are removed rather than just the `<script>` tags — otherwise the "Support US!" heading and the reserved 160x600 gap would remain as an empty titled box. Verified: 0 pages reference googlesyndication |
| Triptych region | **Restored.** "Recent blog posts" / "Recent forum topics" — an entire site-wide region between `#main-wrapper` and the footer. It had been extracted into a partial but never placed in `baseof.html`, so it was silently absent from all 2,655 pages. A frozen snapshot is correct here: nothing new is being posted |
| Comments | Frozen, rendered inline. No new comments |
| Polls | Frozen final results |
| User accounts / login / registration | Removed. Strip every login form, "Log in to post", and `?destination=` link from the output |
| Sidebar "User login" block | Replaced in place by an **"About this archive"** block — same Bartik block styling and position, explaining the site is now read-only. Keeps the sidebar visually balanced and orients returning members |
| Forum posting | Removed; archive is read-only |
| PayPal donate | Static link, works as-is |
| Aggregator feeds | Retire — pulls from external sites that are likely long dead |

### Phase 5 — URL preservation and redirects 

The site is old; its SEO value and inbound links are concentrated in `/node/N` URLs.

- [ ] **Keep `/node/N` working.** Either serve content at those paths, or 301 each to a new
      slug. Do not break them — this is the single highest-risk item for traffic.
- [ ] Redirect `?q=<path>` → `/<path>`, fixing the existing breakage.
- [ ] Preserve `/forum/N`, `/taxonomy/term/N`, `/taxonomy/term/N/all`, `/blog`, `/poll`,
      `/tracker`, `/rss.xml`.
- [ ] Retire `/user/*`, `/node/add/*`, `/comment/reply/*` — 410 Gone is more honest than
      404 for these, and stops search engines retrying.
- [ ] Build the `_redirects` file from the URL manifest captured in Phase 1, not by hand.
- [ ] Custom 404 that offers search, since some breakage is inevitable.

### Phase 6 — QA 

- [x] Crawl the built site and diff the URL manifest against Phase 1's. Every 200 in the
      original should be a 200 or an intentional 301/410 in the new one.
- [x] **Internal link check** (`scripts/check_links.py`): **7 broken links out of 160,895**
      across 2,657 pages. Down from 12,116 at first run. The remaining 5 distinct targets
      were all already broken in the original content — a link to `…/sj/jump7` where the
      file is `jump7.jpg`, `/bo_paradise` where the file is `/files/bo_paradise.jpg`, and a
      malformed fckeditor URL. Left as-is rather than guessed at.
      Getting there fixed two classes of problem: missing pages (`/tracker`, terms with no
      content, the `/forum/21` container, Drupal's `/misc` images) and links to retired
      modules (`/blog/<uid>`, `/faq/<n>`, `/userpoints`, `/messages`, `/aggregator`), which
      are now unwrapped to plain text like the other dead routes.
      Note the checker must treat `//host/path` as *external* — the AdSense script uses a
      protocol-relative URL, and counting it as internal buried the real failures under
      2,641 false positives.
- [ ] **Visual regression pass.** Screenshot a fixed set of page types (front page, article,
      forum thread, taxonomy listing, poll, static page) at 1280px on both the live Drupal
      site and the build, and diff them. Fidelity is a stated requirement, so it gets
      measured rather than eyeballed. Do this while the old site is still up.
- [x] External link report: expect heavy rot across 20 years. Decide whether to leave dead
      links, mark them, or point them at the Wayback Machine.
- [x] Spot-check the oldest content (2005-era) and the most-linked pages by hand.
- [ ] Mobile and Lighthouse pass.
- [x] Confirm no email addresses, IPs or password hashes appear anywhere in `public/`.
      Grep for `@` patterns and for known admin emails before going live.

### Phase 7 — Cutover

- [ ] Deploy to a Netlify Pages preview URL; review against the live Drupal side by side.
- [ ] Point DNS; confirm HTTPS and that `www`/apex both resolve.
- [ ] Submit the new sitemap; watch Search Console for 404 spikes for two weeks.
- [ ] **Do not decommission the old host immediately.** Keep it running (or at least keep a
      full snapshot) for ~30 days after cutover.
- [ ] Archive the final dump encrypted and offline; then decommission.

## 5. Risks and gotchas

- **Dump completeness** — the assumption underpinning Phase 2. Verify in Phase 0, not in
  week three.
- **Spam.** The site has a "Spammer directory" node (`/node/2120`), which strongly implies a
  spam history. A read-only archive makes spam permanent and gives it fresh static URLs.
  Worth a filtering pass on unapproved/spam comments before publishing.
- **Personal data.** Usernames in a public archive are normally defensible; emails and IPs
  are not. GDPR applies (`.no` domain, EEA users), and a frozen archive removes users'
  ability to edit or delete their own posts. Consider an email-based takedown route on the
  contact page.
- **`/node/2120` "Hall of Shame - Spammer directory" is the single riskiest page.**
  Measured after extraction, it contains **86 email addresses and 31 IP addresses**, pairing
  identifiable personal data with a public accusation of spamming. Everything else is
  incidental by comparison: only 15 other files contain any email at all, 2–4 each. Two
  aggravating factors — `filter_url` turns bare addresses into clickable `mailto:` links
  (58 across the corpus), making them harvestable; and a static archive gives the page a
  permanent, re-indexed URL. Options: exclude the node, publish it with the address and IP
  columns redacted, or publish as-is. Recommend redacting at minimum.
- **`/files` is non-standard.** Any tooling that assumes `sites/default/files` will silently
  find nothing. Check the `file_directory_path` variable in the dump.
- **Hotlinked images.** Community posts from 2005–2012 will reference image hosts that no
  longer exist. The crawl cannot recover these; they are already lost.
- **The FCKeditor smileys are gone — and they are everywhere.** Post and comment HTML
  references **4,113** smiley images under `/modules/fckeditor/…/images/smiley/`, spanning
  **1,228 files (455 nodes + 773 comment sets)** — roughly 59% of the archive — across 232
  distinct images. The fckeditor module is absent from `legacy/drupal/` *and* returns 404 on
  the live site, so these are already broken images in production today. Faithfully
  mirroring the current site would mean shipping 4,113 broken images. **Resolved:** replaced
  with Unicode emoji (see Phase 4). This is a deliberate, visible departure from the live
  site — and the one place where matching it exactly would have preserved a defect rather
  than a design.
- **Node ID gaps** — deleted nodes mean `/node/N` is not a dense range. Drive the URL list
  from the database and the crawl, never from a counter.
- **Unpublished content.** The dump may contain drafts never public. Default should be to
  leave them unpublished; publishing them is a deliberate choice, not an accident of migration.
- **AdSense revenue** stops if the ad code is dropped. Small, but should be a decision.

## 6. Open questions

1. **Gamertag generator** — *resolved on feasibility, open on desirability.* It is already
   broken in production (see §1), and the logic is ~20 lines: seed from the name, pick one
   of 67 adjectives and one of 43 nouns. Trivial to reimplement in client-side JS. The only
   real question is whether the output must match what the old generator produced for a
   given name — that requires replicating glibc's `rand()`, which is doable but is the
   difference between an hour's work and most of a day. Given it has been broken for years,
   matching historical output is probably not worth paying for. - Migrate to JS.
2. ~~**AdSense**~~ — *resolved.* Initially kept, then **removed** on 2026-08-17: the archive is ad-free.
3. **Contact form** — external form service, plain mailto, or drop it? Drop it.
4. ~~**Spam and moderation backlog**~~ — *effectively resolved.* Only 27 of 7,245 comments
   are unapproved. Default: exclude those 27, publish the rest. No real decision to make
   unless you want them included. Filter unapporved.
5. **Unpublished nodes** — leave unpublished (default), or review for anything worth
   surfacing? Leave unpublished.
6. **Dead external links** — leave, annotate, or rewrite to Wayback Machine snapshots?
8. **The 13 archived clip videos are `.wmv`** (31.9 MB), a format no current browser plays
   natively — and the Clip Viewer page that framed them (`/node/10`) relied on a Windows
   Media Player ActiveX control, so it is long dead too. They are now copied into the build
   and will download rather than play. Options: leave them as downloadable files, transcode
   to MP4/H.264 (needs ffmpeg; would roughly halve the size and make them playable inline),
   or drop them. Recommend transcoding — they are community-made Burnout clips from
   2007–08 and are probably the least replaceable content on the site.
7. ~~**Smileys**~~ — *resolved.* Mapped to Unicode emoji; 4,183 replaced across 1,267 files,
   none left unmapped. Restoring the original images was ruled out: they are absent from
   `legacy/drupal/` and 404 on the live site, so it would have meant importing a
   third-party asset pack to reproduce something already broken in production. Leave, and rewrite to wayback machine if possible.

## 6b. Completed follow-up work

**Migrate the clip videos to MP4.** *(done — 2026-08-16.)*

31 of 32 referenced clips transcoded from WMV3/VC-1 to MP4/H.264 + AAC,
**378 MB → 261 MB (69%)**, all with `+faststart` so they stream rather than download.
`scripts/transcode_videos.py` is idempotent; `scripts/rewrite_videos.py` converts the links
and runs as a pipeline step.

Three things this turned up:

- **32 clips were referenced, not 13.** The earlier figure counted only direct
  `/videos/X.wmv` hrefs and missed the Clip Viewer's `?wmv=` query form, which accounted for
  19 more, including a whole `burnoutparadise/` subdirectory. The "439 MB of orphaned
  originals" claim was wrong too: the real orphan set is **6 files, 116 MB**.
- **CRF encoding was the wrong tool.** These are high-motion game captures already squeezed
  to ~800 kbps by WMV3. Measured on RocketCar.wmv, CRF 21 produced **163%** of the source
  size and even CRF 27 produced 95%. Bitrate is now set per clip at **0.70x the source**,
  chosen from an SSIM sweep against the original (400k → 0.957, 500k → 0.965, 650k → 0.972,
  800k → 0.978; returns flatten above ~0.965).
- **`t_burnoutparadise_teaser.wmv` is gone** — referenced but absent from the source tree,
  so lost before this project began. Its link degrades to plain text.

Only MP4s are published; shipping the .wmv originals as well would add ~378 MB for a format
nothing can play. **Phase 5 must add a `/videos/*.wmv` → `/videos/*.mp4` redirect** so old
inbound links still resolve.

`/node/10`, the Clip Viewer, is rebuilt as a static index of all 31 clips
(`layouts/_default/clips.html`) — its ActiveX embed and `?wmv=` routing cannot exist on a
static host.

The 6 unreferenced clips (116 MB) remain unpublished. Worth a look before the old host is
decommissioned, in case any deserve to be added.
