#!/usr/bin/env python3
"""
Replace dead FCKeditor smiley <img> tags with Unicode emoji.

The fckeditor module was removed from the site years ago: its images 404 on the
live site and are absent from `legacy/drupal/`. That leaves 4,113 broken images
across ~59% of the archive. Mapping them to emoji needs no third-party assets,
carries no licensing question, renders on every device, and cannot break again.

Each `<img …src=".../smiley/…">` is replaced by the emoji character alone, so it
flows inline exactly where the smiley used to sit.

Usage:  python3 smileys.py [--apply]     (default is a dry run)
"""
import json
import re
import sys
from collections import Counter

from rewrite import CONTENT, DATA, split_frontmatter

# FCKeditor shipped two sets: the MSN Messenger .gif set and a larger .png set.
# Names are matched case-insensitively, extension ignored.
EMOJI = {
    # --- MSN .gif set -----------------------------------------------------
    "teeth_smile": "😃", "regular_smile": "🙂", "wink_smile": "😉",
    "tounge_smile": "😛", "shades_smile": "😎", "confused_smile": "😕",
    "cry_smile": "😢", "sad_smile": "🙁", "angry_smile": "😠",
    "embaressed_smile": "😳", "omg_smile": "😲", "devil_smile": "😈",
    "angel_smile": "😇", "whatchutalkingabout_smile": "😏",
    "thumbs_up": "👍", "thumbs_down": "👎", "heart": "❤️",
    "broken_heart": "💔", "kiss": "💋", "cake": "🍰", "lightbulb": "💡",
    # --- faces (.png set) -------------------------------------------------
    "happy_smiley": "🙂", "very_happy_smiley": "😃",
    "tonque_out_smiley": "😛", "confused_smiley": "😕",
    "winking_smiley": "😉", "crying_smiley": "😢", "sad_smiley": "🙁",
    "angry_smiley": "😠", "angel_smiley": "😇", "nerd_smiley": "🤓",
    "shocked_smiley": "😲", "sarcastic_smiley": "😏",
    "oh_my_god_smiley": "😱", "thinking_smiley": "🤔",
    "sick_smiley": "🤢", "sleepy_smiley": "😴", "hot_smiley": "🥵",
    "dont_know_smiley": "🤷", "ashamed_smiley": "😳",
    "baring_teeth_smiley": "😁", "eye_rolling_smiley": "🙄",
    "dont_tell_anyone_smiley": "🤫", "secret_telling_smiley": "🤫",
    "be_right_back_smiley": "🏃",
    # --- gestures and symbols --------------------------------------------
    "devil": "😈", "fingerscrossed": "🤞", "clapping_hands": "👏",
    "left_hug": "🤗", "right_hug": "🤗", "handcuffs": "⛓️",
    "star": "⭐", "note": "🎵", "light": "💡", "money": "💰",
    "clock": "🕐", "email": "✉️", "messenger": "💬",
    # --- objects ----------------------------------------------------------
    "xbox": "🎮", "auto": "🚗", "airplane": "✈️", "filmstrip": "🎬",
    "computer": "💻", "camera": "📷", "mobile_phone": "📱",
    "soccer_ball": "⚽", "gift": "🎁", "birthday_cake": "🎂",
    "plate": "🍽️", "bowl": "🥣", "beer": "🍺", "dry_martini": "🍸",
    "coffee_cup": "☕", "pizza": "🍕", "cigarette": "🚬",
    # --- nature -----------------------------------------------------------
    "rose": "🌹", "wilted_rose": "🥀", "island": "🏝️", "snail": "🐌",
    "turtle": "🐢", "cat": "🐱", "dog": "🐶", "goat": "🐐",
    "sheep": "🐑", "bat": "🦇", "sun": "☀️", "moon": "🌙",
    "rain": "🌧️", "storm": "⛈️", "rainbow": "🌈", "umbrella": "☂️",
    # --- people -----------------------------------------------------------
    "girl": "👧", "boy": "👦",
}

IMG = re.compile(r"<img\b[^>]*?src=\"[^\"]*?/smiley/[^\"]*?\"[^>]*?>", re.I)
NAME = re.compile(r"/smiley/[^\"]*?/([^/\"]+?)\.(?:png|gif|jpe?g)", re.I)

replaced = Counter()
unmapped = Counter()


def sub_smileys(html):
    def repl(m):
        tag = m.group(0)
        nm = NAME.search(tag)
        if not nm:
            unmapped["<unparseable src>"] += 1
            return tag
        key = nm.group(1).lower()
        if key in EMOJI:
            replaced[key] += 1
            return EMOJI[key]
        unmapped[key] += 1
        return tag  # leave untouched so it shows up in the report

    return IMG.sub(repl, html)


def main():
    apply = "--apply" in sys.argv
    changed = 0

    for p in sorted(CONTENT.rglob("*.html")):
        text = p.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        new = sub_smileys(body)
        if new != body:
            changed += 1
            if apply:
                p.write_text(fm + new, encoding="utf-8")

    for p in sorted((DATA / "comments").glob("*.json")):
        rows = json.loads(p.read_text(encoding="utf-8"))
        dirty = False
        for c in rows:
            nb = sub_smileys(c.get("body", ""))
            if nb != c.get("body", ""):
                c["body"] = nb
                dirty = True
        if dirty:
            changed += 1
            if apply:
                p.write_text(
                    json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8"
                )

    print("DRY RUN — nothing written (pass --apply)" if not apply else "APPLIED")
    print(f"files changed:    {changed}")
    print(f"smileys replaced: {sum(replaced.values())} across {len(replaced)} distinct images")
    if unmapped:
        print(f"\nUNMAPPED ({sum(unmapped.values())} refs, {len(unmapped)} names):")
        for k, v in unmapped.most_common():
            print(f"  {v:>5}  {k}")
    else:
        print("unmapped: none — every smiley in the archive has an emoji")


if __name__ == "__main__":
    main()
