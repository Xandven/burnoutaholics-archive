#!/usr/bin/env python3
"""
Minimal reader for per-table mysqldump files (extended INSERT format).

No MySQL server required. Parses `INSERT INTO `t` VALUES (...),(...);`
statements into Python rows, honouring MySQL's backslash escaping and
NULL literals. Column names come from the CREATE TABLE block.

Usage as a library:
    from dumpq import read_table
    cols, rows = read_table('legacy/db/burnoutaholics_com_node.sql')
"""
import re
import sys
from pathlib import Path

# MySQL backslash escape sequences as emitted by mysqldump.
_UNESCAPE = {
    "0": "\0", "b": "\b", "n": "\n", "r": "\r",
    "t": "\t", "Z": "\x1a", "\\": "\\", "'": "'", '"': '"',
}


def _parse_values(s, i):
    """Parse one `( ... )` tuple starting at s[i] == '('. Returns (row, next_i)."""
    assert s[i] == "("
    i += 1
    row, buf, in_str = [], [], False
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "\\" and i + 1 < len(s):
                row_c = s[i + 1]
                buf.append(_UNESCAPE.get(row_c, row_c))
                i += 2
                continue
            if c == "'":
                # Doubled '' inside a string is a literal quote.
                if i + 1 < len(s) and s[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_str = False
                i += 1
                continue
            buf.append(c)
            i += 1
            continue
        if c == "'":
            in_str = True
            i += 1
            continue
        if c in ",)":
            tok = "".join(buf).strip()
            # Only an unquoted, bare NULL is a real NULL.
            row.append(None if tok == "NULL" else tok)
            buf = []
            i += 1
            if c == ")":
                return row, i
            continue
        buf.append(c)
        i += 1
    raise ValueError("unterminated tuple")


def read_table(path, limit=None):
    """Return (columns, rows) for a single-table dump file."""
    raw = Path(path).read_bytes()
    # Dumps are byte-exact; decode permissively so odd encodings survive.
    text = raw.decode("utf-8", errors="surrogateescape")

    cols = re.findall(r"^\s{2}`([^`]+)`\s", text, re.M)

    rows = []
    for m in re.finditer(r"INSERT INTO `[^`]+` VALUES ", text):
        i = m.end()
        while i < len(text):
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            if i >= len(text) or text[i] != "(":
                break
            row, i = _parse_values(text, i)
            rows.append(row)
            if limit and len(rows) >= limit:
                return cols, rows
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            if i < len(text) and text[i] == ",":
                i += 1
                continue
            break
    return cols, rows


def count_rows(path):
    return len(read_table(path)[1])


if __name__ == "__main__":
    for p in sys.argv[1:]:
        cols, rows = read_table(p)
        print(f"{Path(p).name}: {len(rows)} rows, {len(cols)} cols")
        print(f"  cols: {', '.join(cols[:12])}{' …' if len(cols) > 12 else ''}")
