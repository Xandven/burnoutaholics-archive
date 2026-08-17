#!/usr/bin/env python3
"""
Transcode the archived .wmv clips to MP4/H.264 so browsers can actually play them.

The clips are 2007–08 community captures in Windows Media (WMV3/VC-1 + WMAV2), a
format no current browser plays natively. The Clip Viewer page that framed them
used a Windows Media Player ActiveX control and has been dead for years.

Discovery covers both link forms — a direct `/videos/X.wmv` href and the clip
viewer's `?wmv=X` query parameter. Only counting the first finds 13 clips; the
real figure is 32, including a whole `burnoutparadise/` subdirectory.

Only MP4s are published. Shipping the .wmv originals as well would add ~378 MB to
the repository for a format nothing can play; old `/videos/X.wmv` URLs are
handled with a redirect instead (see PLAN.md §5).

Idempotent: a clip whose .mp4 already exists and is newer than the source is
skipped, so this can be re-run cheaply.

Usage:  python3 transcode_videos.py [--apply] [--force]
"""
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "legacy" / "drupal" / "videos"
OUT = ROOT / "static" / "videos"
CONTENT = ROOT / "content"
DATA = ROOT / "data"

DIRECT = re.compile(r'href="/videos/([^"]+\.wmv)"', re.I)
VIEWER = re.compile(r'href="/node/10\?[^"]*wmv=([^&"]+\.wmv)', re.I)

# Bitrate is set per clip, not by a fixed CRF.
#
# These are high-motion game captures already squeezed to ~800 kbps by WMV3, so
# CRF targeting badly overshoots: measured on RocketCar.wmv, even CRF 27 came out
# at 95% of the source size and CRF 21 at 163%. Targeting a fraction of each
# clip's own bitrate adapts to the 320x240 clips as well as the 640x480 ones.
#
# 0.70 chosen from an SSIM sweep against the source (higher is closer):
#     400 kbps  67% of source  SSIM 0.957
#     500 kbps  80% of source  SSIM 0.965
#     650 kbps 100% of source  SSIM 0.972
#     800 kbps 121% of source  SSIM 0.978
# Returns flatten above ~0.965, and H.264 at 70% of a WMV3 bitrate is a fair
# trade — the codec is markedly more efficient than the one being replaced.
BITRATE_RATIO = 0.70
MIN_VIDEO_KBPS = 250


def source_video_kbps(path):
    """Video-stream bitrate in kbps, falling back to container bitrate."""
    for args in (
        ["-select_streams", "v:0", "-show_entries", "stream=bit_rate"],
        ["-show_entries", "format=bit_rate"],
    ):
        r = subprocess.run(
            ["ffprobe", "-v", "error", *args, "-of", "csv=p=0", str(path)],
            capture_output=True,
        )
        val = r.stdout.decode(errors="replace").strip().split("\n")[0]
        if val.isdigit() and int(val) > 0:
            return int(val) / 1000
    return 800.0


def ffmpeg_args(src):
    kbps = max(MIN_VIDEO_KBPS, round(source_video_kbps(src) * BITRATE_RATIO))
    return [
        "-c:v", "libx264", "-b:v", f"{kbps}k",
        "-maxrate", f"{int(kbps * 1.5)}k", "-bufsize", f"{kbps * 3}k",
        "-preset", "slow", "-profile:v", "high", "-pix_fmt", "yuv420p",
        # Odd dimensions break yuv420p; force even without rescaling anything real.
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:a", "aac", "-b:a", "96k", "-ar", "44100",
        "-movflags", "+faststart",
    ]


def referenced():
    out = set()
    for p in list(CONTENT.rglob("*.html")) + list((DATA / "comments").glob("*.json")):
        t = p.read_text(encoding="utf-8", errors="replace")
        for m in DIRECT.finditer(t):
            out.add(urllib.parse.unquote(m.group(1)))
        for m in VIEWER.finditer(t):
            out.add(urllib.parse.unquote(m.group(1)))
    return sorted(out)


def main():
    apply = "--apply" in sys.argv
    force = "--force" in sys.argv

    todo, missing, skipped = [], [], []
    for rel in referenced():
        src = SRC / rel
        if not src.is_file():
            missing.append(rel)
            continue
        dst = OUT / (rel[:-4] + ".mp4")
        if dst.is_file() and not force and dst.stat().st_mtime >= src.stat().st_mtime:
            skipped.append(rel)
            continue
        todo.append((rel, src, dst))

    print(f"referenced clips: {len(todo) + len(skipped) + len(missing)}")
    print(f"  to transcode: {len(todo)}   already done: {len(skipped)}   "
          f"source missing: {len(missing)}")
    for m in missing:
        print(f"    MISSING  {m}")
    if not apply:
        print("\nDRY RUN — pass --apply to transcode")
        return 0

    src_total = out_total = 0
    for i, (rel, src, dst) in enumerate(todo, 1):
        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(src), *ffmpeg_args(src), str(dst)]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0 or not dst.is_file():
            print(f"  [{i}/{len(todo)}] FAILED {rel}")
            print("    " + r.stderr.decode(errors="replace").strip()[:300])
            continue
        s, d = src.stat().st_size, dst.stat().st_size
        src_total += s
        out_total += d
        print(f"  [{i}/{len(todo)}] {rel}  {s/1e6:.1f} → {d/1e6:.1f} MB "
              f"({100 * d / s:.0f}%)", flush=True)

    if src_total:
        print(f"\ntotal: {src_total/1e6:.0f} MB → {out_total/1e6:.0f} MB "
              f"({100 * out_total / src_total:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
