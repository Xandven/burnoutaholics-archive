#!/usr/bin/env python3
"""
Python port of the Drupal 7 text filters this site actually uses.

SPDX-License-Identifier: GPL-2.0-or-later

Unlike the rest of scripts/ (MIT), this file is GPL-2.0-or-later: `filter_autop`
below is a direct translation of Drupal 7's `_filter_autop()`, and a translation
is a derivative work of the original GPL source. See LICENSE.

Fidelity matters more than elegance here: the goal is to reproduce byte-for-byte
what Drupal produced, including its quirks, so the static build matches the live
site. Where Drupal's regex is odd (e.g. `<p` in the block-tag pattern also
matching `<param>`), the oddity is preserved deliberately.

Formats in use on this site (from `filter_format` / `filter`):

  format 1 "Filtered HTML"  filter_url(0) → filter_html(1) → filter_autop(2) → htmlcorrector(11)
  format 2 "PHP code"       executed PHP — cannot be rendered offline, handled separately
  format 3 "Full HTML"      filter_url(0) → filter_autop(1) → htmlcorrector(11)
  format 4 "Plain text"     filter_html_escape(0) → filter_url(1) → filter_autop(2)
"""
import re
from html import escape as _html_escape
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Encoding repair
# ---------------------------------------------------------------------------

# Signature of UTF-8 bytes that were re-encoded as if they were cp1252/latin1.
_MOJIBAKE = re.compile(r"Ã.|â€.|Â.")


def _to_original_bytes(s):
    """Reverse a cp1252 misreading, character by character.

    Neither codec works alone on real data. Pure cp1252 cannot encode C1
    characters such as U+009D (the tail of a double-encoded `"`), and pure
    latin-1 cannot encode U+20AC (`€`, the 0x80 byte that starts most of these
    sequences). Real mojibake mixes both, so each character is mapped with
    cp1252 where it has a mapping and by raw code point otherwise.
    """
    out = bytearray()
    for ch in s:
        try:
            out += ch.encode("cp1252")
        except UnicodeEncodeError:
            if ord(ch) < 256:
                out.append(ord(ch))
            else:
                return None
    return bytes(out)


def repair_mojibake(s):
    """Selectively undo double-encoding.

    The `node` and `comment` tables are latin1 while bodies are utf8, so the
    data is a *mix* of correctly-encoded and double-encoded strings. Applying a
    blanket re-decode would corrupt the strings that are already right, so only
    strings showing the mojibake signature are touched, and only when the
    round-trip actually removes the signature.
    """
    if not s or not _MOJIBAKE.search(s):
        return s
    raw = _to_original_bytes(s)
    if raw is not None:
        try:
            fixed = raw.decode("utf-8")
        except UnicodeDecodeError:
            fixed = None
        if fixed and not _MOJIBAKE.search(fixed):
            return fixed
    return s  # leave anything we cannot confidently repair


# ---------------------------------------------------------------------------
# filter_autop  (direct port of Drupal 7 _filter_autop)
# ---------------------------------------------------------------------------

_BLOCK = (
    r"(?:table|thead|tfoot|caption|colgroup|col|tbody|tr|td|th|div|dl|dd|dt|ul|ol"
    r"|li|pre|select|form|blockquote|address|p|h[1-6]|hr|article|aside|details"
    r"|figcaption|figure|footer|header|hgroup|menu|nav|section|summary)"
)

_SPLIT_IGNORE = re.compile(
    r"(<!--.*?-->|</?(?:pre|script|style|object|iframe|!--)[^>]*>)", re.S | re.I
)


def filter_autop(text):
    if text is None:
        return ""
    chunks = _SPLIT_IGNORE.split(text)
    ignore, ignoretag, out = False, "", []

    for i, chunk in enumerate(chunks):
        if i % 2:
            # Delimiter: a pre/script/style/object/iframe tag, or a comment.
            if chunk.startswith("<!--"):
                out.append(chunk)
                continue
            is_open = len(chunk) > 1 and chunk[1] != "/"
            start = 1 if is_open else 2
            tag = re.split(r"[ >]", chunk[start:], 1)[0]
            if not ignore:
                if is_open:
                    ignore, ignoretag = True, tag
            elif not is_open and ignoretag == tag:
                ignore, ignoretag = False, ""
            out.append(chunk)
            continue

        if ignore:
            out.append(chunk)
            continue

        c = re.sub(r"\n+$", "", chunk) + "\n\n"
        c = re.sub(r"<br />\s*<br />", "\n\n", c)
        c = re.sub(r"(<" + _BLOCK + r"[^>]*>)", r"\n\1", c)
        c = re.sub(r"(</" + _BLOCK + r">)", r"\1\n\n", c)
        c = re.sub(r"\n\n+", "\n\n", c)
        c = re.sub(r"^\n|\n$", "", c)
        c = "<p>" + re.sub(r"\n\s*\n\n?(.)", r"</p>\n<p>\1", c) + "</p>\n"
        c = re.sub(r"<p>(<li.+?)</p>", r"\1", c, flags=re.S)
        c = re.sub(r"<p><blockquote([^>]*)>", r"<blockquote\1><p>", c, flags=re.I)
        c = c.replace("</blockquote></p>", "</p></blockquote>")
        c = re.sub(r"<p>\s*(</?" + _BLOCK + r"[^>]*>)", r"\1", c)
        c = re.sub(r"(</?" + _BLOCK + r"[^>]*>)\s*</p>", r"\1", c)
        c = re.sub(r"(?<!<br />)\s*\n", "<br />\n", c)
        c = re.sub(r"(</?" + _BLOCK + r"[^>]*>)\s*<br />", r"\1", c)
        c = re.sub(
            r"<br />(\s*</?(?:p|li|div|dl|dd|dt|th|pre|td|ul|ol)[^>]*>)", r"\1", c
        )
        c = re.sub(r"&([^#])(?![A-Za-z0-9]{1,8};)", r"&amp;\1", c)
        out.append(c)

    return "".join(out)


# ---------------------------------------------------------------------------
# filter_url  (port of Drupal 7 _filter_url, simplified but behaviour-compatible)
# ---------------------------------------------------------------------------

_PROTOCOLS = r"(?:https?|ftp|news|nntp|tel|telnet|mailto|irc|ssh|sftp|webcal|rtsp)"

# Skip anything already inside a tag or an anchor.
_SKIP = re.compile(r"(<a\b.*?</a>|<[^>]*>|&[A-Za-z0-9#]+;)", re.S | re.I)

# One combined pattern, matched in a single pass. Matching each kind of link
# separately re-scans markup the previous pass just created, which produces
# nested <a href="http://<a href=...">> garbage.
_LINKIFY = re.compile(
    r"("
    + _PROTOCOLS
    + r"://[^\s<>\"'()]+[^\s<>\"'().,;:!?]"
    r"|www\.[^\s<>\"'()]+[^\s<>\"'().,;:!?]"
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r")"
)


def _trim(text, length):
    """Drupal truncates the *visible* text of auto-created links."""
    if length and len(text) > length:
        return text[: length - 1] + "…"
    return text


def filter_url(text, length=72):
    if not text:
        return ""

    def _link(m):
        s = m.group(1)
        if "://" in s:
            href = s
        elif s.startswith("www."):
            href = "http://" + s
        else:
            href = "mailto:" + s
        return f'<a href="{href}">{_trim(s, length)}</a>'

    def linkify(segment):
        return _LINKIFY.sub(_link, segment)

    parts = _SKIP.split(text)
    # Even indices are plain text, odd indices are protected markup.
    return "".join(
        p if i % 2 else linkify(p) for i, p in enumerate(parts) if p is not None
    )


# ---------------------------------------------------------------------------
# filter_html  (allowed-tag stripping, as configured for format 1)
# ---------------------------------------------------------------------------

FORMAT1_ALLOWED = {
    "a", "em", "strong", "cite", "code", "ul", "ol", "li", "dl", "dt", "dd",
    "img", "p", "br", "b", "span", "u", "i", "blockquote", "font", "table",
    "tr", "th", "td", "h1", "h2", "h3", "h4", "h5", "h6", "tt", "thead",
    "tfoot", "div", "embed",
}

# NB: `embed` is deliberately absent. Old Flash markup nests <embed> inside
# <object> and closes it explicitly; treating it as void drops the </embed> and
# diverges from what the live site serves.
_VOID = {"br", "img", "hr", "input", "meta", "link", "col", "area", "base"}

_EVENT_ATTR = re.compile(r"^on", re.I)
_BAD_URL = re.compile(r"^\s*(javascript|vbscript|data)\s*:", re.I)
_URL_ATTR = {"href", "src", "action", "formaction", "background", "poster"}


class _TagFilter(HTMLParser):
    """Strip tags outside the allowed set, keeping their inner content.

    Also drops event-handler attributes and script-ish URLs — Drupal's
    filter_xss does the same, and it matters because this content is
    user-submitted and 20 years old.
    """

    def __init__(self, allowed):
        super().__init__(convert_charrefs=False)
        self.allowed = allowed
        self.out = []

    def _attrs(self, attrs):
        parts = []
        for k, v in attrs:
            if _EVENT_ATTR.match(k):
                continue
            # Drupal 7's filter_xss drops `style` outright. Other presentational
            # attributes (e.g. `size` on <font>) survive, so this is specific to
            # style rather than a general attribute purge.
            if k.lower() == "style":
                continue
            if v is None:
                parts.append(f" {k}")
                continue
            if k.lower() in _URL_ATTR and _BAD_URL.match(v):
                continue
            parts.append(f' {k}="{_html_escape(v, quote=True)}"')
        return "".join(parts)

    def handle_starttag(self, tag, attrs):
        if tag in self.allowed:
            slash = " /" if tag in _VOID else ""
            self.out.append(f"<{tag}{self._attrs(attrs)}{slash}>")

    def handle_startendtag(self, tag, attrs):
        if tag in self.allowed:
            self.out.append(f"<{tag}{self._attrs(attrs)} />")

    def handle_endtag(self, tag):
        if tag in self.allowed and tag not in _VOID:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        self.out.append(data)

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")

    def handle_comment(self, data):
        pass  # Drupal's filter_xss drops comments

    def result(self):
        return "".join(self.out)


def filter_html(text, allowed=None):
    if not text:
        return ""
    p = _TagFilter(allowed or FORMAT1_ALLOWED)
    p.feed(text)
    p.close()
    return p.result()


# ---------------------------------------------------------------------------
# filter_htmlcorrector  (balance tags — Drupal uses DOM load/serialise)
# ---------------------------------------------------------------------------


# Elements whose open tag implicitly closes a currently-open element. Drupal
# gets this free from DOMDocument; we have to state it. Without it, sequences
# like `<p>a<p>b` nest instead of siblings, which diverges from the live site.
_CLOSES_P = {
    "address", "article", "aside", "blockquote", "div", "dl", "fieldset",
    "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
    "main", "nav", "ol", "p", "pre", "section", "table", "ul",
}
_IMPLIED_END = {
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "tr": {"tr"},
    "td": {"td", "th", "tr"},
    "th": {"td", "th", "tr"},
    "option": {"option"},
    "p": _CLOSES_P,
}


class _Corrector(HTMLParser):
    """Balance tags and resolve entities, mirroring DOMDocument round-tripping.

    `convert_charrefs=True` makes the parser decode `&hellip;` and friends into
    real characters, which is what Drupal's filter_dom_load/serialize pair does.
    Text is then re-escaped for the three XML-significant characters only.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []

    def _close_implied(self, tag):
        while self.stack:
            top = self.stack[-1]
            if tag in _IMPLIED_END.get(top, ()):
                self.out.append(f"</{self.stack.pop()}>")
            else:
                break

    def handle_starttag(self, tag, attrs):
        self._close_implied(tag)
        self.out.append(self.get_starttag_text() or f"<{tag}>")
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.out.append(self.get_starttag_text() or f"<{tag} />")

    def handle_endtag(self, tag):
        if tag in _VOID or tag not in self.stack:
            return  # void or stray close tag — drop it
        while self.stack:
            top = self.stack.pop()
            self.out.append(f"</{top}>")
            if top == tag:
                break

    def handle_data(self, data):
        self.out.append(
            data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )

    def handle_comment(self, data):
        self.out.append(f"<!--{data}-->")

    def result(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def filter_htmlcorrector(text):
    if not text:
        return ""
    p = _Corrector()
    p.feed(text)
    p.close()
    return p.result()


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------


def render(text, fmt):
    """Run `text` through the filter chain configured for `fmt`."""
    fmt = str(fmt)
    if text is None:
        return ""
    # Bodies are stored with CRLF (HTTP form submission), but the rendered
    # output on the live site matches LF-only input. Without this, autop's
    # `(?<!<br />)\s*\n` rule fires on the \n after a \r and emits a doubled
    # <br />. Verified against node/1684: exact match only with this in place.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if fmt == "1":  # Filtered HTML
        return filter_htmlcorrector(filter_autop(filter_html(filter_url(text))))
    if fmt == "3":  # Full HTML
        return filter_htmlcorrector(filter_autop(filter_url(text)))
    if fmt == "4":  # Plain text
        return filter_autop(filter_url(_html_escape(text, quote=False)))
    if fmt == "2":  # PHP code — cannot be rendered without executing it
        raise ValueError("format 2 (PHP code) must be sourced from the crawl")
    return filter_htmlcorrector(filter_autop(text))
