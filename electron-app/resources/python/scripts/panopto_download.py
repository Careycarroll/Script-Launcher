#!/usr/bin/env python3
"""
panopto_download.py — Download Panopto lecture videos via yt-dlp.

v1 accepts Panopto viewer URLs only. Canvas URL auto-resolution was
investigated but cut: UNC Canvas is a React SPA behind SAML SSO — the
Panopto embed URL is only in the DOM after JavaScript executes, which
requires a headless browser (Playwright) to scrape reliably. The
Electron UI provides a "Copy console command" button that gives users
a one-liner to paste into Canvas DevTools to grab the Panopto URL in
~5 seconds. Tracked as a future issue.

Emits line-delimited JSON on stdout:
  {"type": "info",     "message": "..."}
  {"type": "progress", "percent": N, "eta_seconds": N, "speed_bps": N,
                       "downloaded_bytes": N, "total_bytes": N}
  {"type": "conflict", "path": "...", "message": "File exists"}
  {"type": "done",     "path": "/absolute/path/to/file.mp4"}
  {"type": "error",    "message": "..."}

For conflicts, script pauses and reads ONE line from stdin:
  {"action": "cancel"}          -> emits error, exits
  {"action": "overwrite"}       -> deletes existing files, resumes
  {"action": "increment"}       -> auto-picks next available number, resumes

CLI:
  panopto_download.py <panopto-url> --out-dir DIR --prefix NN [flags]

Flags:
  --out-dir PATH                 Required. Output directory.
  --prefix NN                    Required. Two-digit number prefix.
  --quality {best,1080p,720p}    Default: best
  --captions/--no-captions       Default: on
  --embed-subs/--no-embed-subs   Default: on (embed vtt into container)
  --browser NAME                 Default: zen (see BROWSERS)
  --concurrent-fragments N       Default: 4
  --retries N                    Default: 10
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import threading
from pathlib import Path
from typing import Optional

import yt_dlp


# Browser -> yt-dlp cookies-from-browser argument.
# Zen is Firefox-schema; point yt-dlp at its profile dir.
ZEN_PROFILE = str(Path.home() / 'Library/Application Support/zen/Profiles/et1dknsr.Default (release)')
BROWSERS = {
    'zen':     f'firefox:{ZEN_PROFILE}',
    'firefox': 'firefox',
    'chrome':  'chrome',
    'safari':  'safari',
    'brave':   'brave',
    'edge':    'edge',
    'none':    None,
}

QUALITY_FORMATS = {
    # Panopto serves combined HLS streams (video+audio in one file), not
    # separate tracks. 'best' picks the single-file stream with highest
    # resolution/bitrate. bv+ba fallbacks handle sites that do split them.
    'best':  'best[height>=1080]/best[height>=720]/best',
    '1080p': 'best[height<=1080][height>=1080]/best[height<=1080]',
    '720p':  'best[height<=720]',
}



def pick_metadata_format(info: dict, quality: str) -> dict | None:
    """
    Pick the format we expect yt-dlp to download, for metadata display only.
    Panopto serves combined HLS video+audio streams, so prefer formats with
    real dimensions and ignore PODCAST/unknown formats.
    """
    formats = info.get('formats') or []
    video_formats = [
        f for f in formats
        if f.get('height') and f.get('width') and f.get('vcodec') != 'none'
    ]
    if not video_formats:
        return None

    def score(f):
        return (f.get('height') or 0, f.get('tbr') or 0)

    if quality == '720p':
        candidates = [f for f in video_formats if (f.get('height') or 0) <= 720]
        return max(candidates or video_formats, key=score)

    if quality == '1080p':
        candidates = [f for f in video_formats if (f.get('height') or 0) <= 1080]
        return max(candidates or video_formats, key=score)

    # best
    return max(video_formats, key=score)


def estimate_filesize_bytes(fmt: dict | None, duration_seconds: float | None) -> int | None:
    """Use filesize if present; otherwise estimate from total bitrate."""
    if not fmt:
        return None
    size = fmt.get('filesize') or fmt.get('filesize_approx')
    if size:
        return int(size)
    tbr = fmt.get('tbr')  # kilobits/sec
    if tbr and duration_seconds:
        return int((float(tbr) * 1000 / 8) * float(duration_seconds))
    return None

# ── Emit helpers ──
def emit(**kwargs):
    sys.stdout.write(json.dumps(kwargs) + '\n')
    sys.stdout.flush()


def read_action() -> str:
    """Block until parent sends {'action': 'cancel'|'overwrite'|'increment'}."""
    line = sys.stdin.readline().strip()
    if not line:
        return 'cancel'
    try:
        msg = json.loads(line)
        return msg.get('action', 'cancel')
    except json.JSONDecodeError:
        return 'cancel'


# ── URL validation ──
def validate_panopto_url(url: str) -> str:
    """Ensure the URL is a Panopto Viewer or Embed URL. Anything else rejected."""
    if 'panopto.com' in url and ('Viewer.aspx' in url or 'Embed.aspx' in url):
        return url
    raise RuntimeError()


# ── Numbering ──
NUM_PREFIX_RE = re.compile(r'^(\d+)\.\s')


def next_available_prefix(out_dir: Path) -> int:
    """Scan directory for files matching NN. * and return max+1."""
    max_n = 0
    for p in out_dir.iterdir():
        m = NUM_PREFIX_RE.match(p.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def files_matching_prefix(out_dir: Path, prefix: str) -> list[Path]:
    """Return files starting with '<prefix>. ' regardless of extension."""
    return [p for p in out_dir.iterdir() if p.name.startswith(f'{prefix}. ')]



# ── File-size progress monitor ────────────────────────────────────────────────
def monitored_bytes_for_prefix(out_dir: Path, prefix: str) -> int:
    """
    Sum bytes for any output/temp files starting with '<prefix>. '.
    yt-dlp may write .part/.ytdl/temp files while post-processing, so this is
    more reliable for Panopto HLS than yt-dlp's Python progress hooks.
    """
    total = 0
    for p in out_dir.iterdir():
        if p.name.startswith(f'{prefix}. '):
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def start_filesize_monitor(out_dir: Path, prefix: str, total_bytes: int | None, stop_event: threading.Event):
    """
    Emit progress based on observed file size.

    yt-dlp's Python progress hooks do not reliably fire for this Panopto HLS
    path, so we monitor files beginning with '<prefix>. ' instead.

    Smoothing choices:
      - emit on a fixed 0.5s cadence
      - keep downloaded bytes monotonic
      - compute speed from deltas
      - smooth speed with an exponential moving average
      - estimate ETA from smoothed speed
    """
    if not total_bytes or total_bytes <= 0:
        return None

    def run():
        interval = 0.5
        alpha = 0.25  # EMA smoothing factor; lower = smoother, slower to react

        last_time = time.time()
        last_bytes = 0
        max_bytes = 0
        ema_speed = 0.0

        while not stop_event.is_set():
            now = time.time()
            observed = monitored_bytes_for_prefix(out_dir, prefix)

            # File size can briefly shrink during rename/post-process. Never
            # show backwards progress.
            max_bytes = max(max_bytes, observed)
            downloaded = min(max_bytes, total_bytes)

            elapsed = max(now - last_time, 0.001)
            delta = max(downloaded - last_bytes, 0)
            instant_speed = delta / elapsed

            if instant_speed > 0:
                ema_speed = instant_speed if ema_speed <= 0 else (alpha * instant_speed + (1 - alpha) * ema_speed)
            else:
                # Decay slowly during segment stalls / post-processing pauses.
                ema_speed *= 0.90

            percent = min(99.0, (downloaded / total_bytes) * 100)
            remaining = max(total_bytes - downloaded, 0)
            eta = int(remaining / ema_speed) if ema_speed > 1 else 0

            emit(
                type='progress',
                percent=round(percent, 1),
                eta_seconds=eta,
                speed_bps=int(ema_speed),
                downloaded_bytes=int(downloaded),
                total_bytes=int(total_bytes),
            )

            last_time = now
            last_bytes = downloaded
            stop_event.wait(interval)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


# ── Progress hook ──
_last_progress = [0.0]  # rate-limit to ~1/sec


def progress_hook(d):
    if d['status'] == 'downloading':
        now = time.time()
        if now - _last_progress[0] < 0.25:
            return
        _last_progress[0] = now
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes') or 0
        percent = (downloaded / total * 100) if total else 0
        emit(
            type='progress',
            percent=round(percent, 1),
            eta_seconds=d.get('eta') or 0,
            speed_bps=d.get('speed') or 0,
            downloaded_bytes=downloaded,
            total_bytes=total,
        )
    elif d['status'] == 'finished':
        emit(type='info', message='Download complete, post-processing...')


# ── Main ──
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('url')
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--prefix', required=True, help='Two-digit number prefix')
    parser.add_argument('--quality', default='best', choices=list(QUALITY_FORMATS))
    parser.add_argument('--captions', dest='captions', action='store_true', default=True)
    parser.add_argument('--no-captions', dest='captions', action='store_false')
    parser.add_argument('--embed-subs', dest='embed_subs', action='store_true', default=True)
    parser.add_argument('--no-embed-subs', dest='embed_subs', action='store_false')
    parser.add_argument('--browser', default='zen', choices=list(BROWSERS))
    parser.add_argument('--concurrent-fragments', type=int, default=4)
    parser.add_argument('--retries', type=int, default=10)
    args = parser.parse_args()

    out_dir = args.out_dir.expanduser().resolve()
    if not out_dir.is_dir():
        emit(type='error', message=f'not a directory: {out_dir}')
        return 1

    try:
        target_url = validate_panopto_url(args.url)
    except RuntimeError as e:
        emit(type='error', message=str(e))
        return 1

    prefix = args.prefix

    # Check for conflicts. yt-dlp names files as "<prefix>. <title>.<ext>".
    # We can't know the title yet, but files starting with "<prefix>. " would collide.
    existing = files_matching_prefix(out_dir, prefix)
    if existing:
        emit(
            type='conflict',
            path=str(existing[0]),
            message=f'{len(existing)} file(s) already start with "{prefix}. "',
        )
        action = read_action()
        if action == 'cancel':
            emit(type='error', message='cancelled by user')
            return 1
        elif action == 'overwrite':
            for p in existing:
                try:
                    p.unlink()
                    emit(type='info', message=f'Deleted: {p.name}')
                except OSError as e:
                    emit(type='error', message=f'could not delete {p.name}: {e}')
                    return 1
        elif action == 'increment':
            new_num = next_available_prefix(out_dir)
            prefix = f'{new_num:02d}'
            emit(type='info', message=f'Using prefix {prefix} instead')

    # Build yt-dlp options.
    ydl_opts = {
        'outtmpl': str(out_dir / f'{prefix}. %(title)s.%(ext)s'),
        'format': QUALITY_FORMATS[args.quality],
        'concurrent_fragment_downloads': args.concurrent_fragments,
        'retries': args.retries,
        'progress_hooks': [progress_hook],
        'quiet': True,
        'no_warnings': True,
    }
    if args.captions:
        ydl_opts['writesubtitles'] = True
        ydl_opts['subtitleslangs'] = ['en', 'en-US', 'en.*']
        if args.embed_subs:
            # For MP4 output, subs must be converted to mov_text.
            # postprocessor: FFmpegEmbedSubtitle handles the conversion.
            ydl_opts['embedsubtitles'] = True
            ydl_opts['merge_output_format'] = 'mp4'
            # Don't specify subtitlesformat when embedding — let yt-dlp pick
            # the best source format for the post-processor to convert.
            ydl_opts['postprocessors'] = [
                {'key': 'FFmpegEmbedSubtitle', 'already_have_subtitle': False},
            ]
        else:
            # Sidecar only — user wants a separate .vtt file.
            ydl_opts['subtitlesformat'] = 'vtt'
    cookie_arg = BROWSERS[args.browser]
    if cookie_arg:
        if ':' in cookie_arg:
            browser_name, profile_path = cookie_arg.split(':', 1)
            ydl_opts['cookiesfrombrowser'] = (browser_name, profile_path, None, None)
        else:
            ydl_opts['cookiesfrombrowser'] = (cookie_arg, None, None, None)

    emit(type='info', message='Fetching video metadata...')

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Probe without downloading to emit metadata for the UI.
            probe = ydl.extract_info(target_url, download=False)
            selected = pick_metadata_format(probe, args.quality)
            original_title = probe.get('title', '')
            duration_seconds = probe.get('duration')
            metadata_filesize = estimate_filesize_bytes(selected, duration_seconds)
            emit(
                type='metadata',
                title=original_title,
                width=selected.get('width') if selected else None,
                height=selected.get('height') if selected else None,
                filesize=metadata_filesize,
                duration_seconds=duration_seconds,
                format_id=selected.get('format_id') if selected else None,
                fps=selected.get('fps') if selected else None,
            )

            # Wait for user confirmation:
            #   {"action": "confirm", "title": "optional edited title"}
            #   {"action": "cancel"}
            confirm_line = sys.stdin.readline().strip()
            try:
                confirm_msg = json.loads(confirm_line) if confirm_line else {'action': 'cancel'}
            except json.JSONDecodeError:
                confirm_msg = {'action': 'cancel'}

            if confirm_msg.get('action') != 'confirm':
                emit(type='error', message='cancelled by user')
                return 1

            edited_title = (confirm_msg.get('title') or original_title).strip()
            if edited_title != original_title:
                safe = edited_title.replace('%', '%%')
                ydl_opts['outtmpl'] = str(out_dir / f'{prefix}. {safe}.%(ext)s')

            emit(type='info', message='Starting download...')
            emit(
                type='progress',
                percent=0,
                eta_seconds=0,
                speed_bps=0,
                downloaded_bytes=0,
                total_bytes=metadata_filesize or 0,
            )
        # Fresh instance so any changed outtmpl takes effect.
        stop_monitor = threading.Event()
        monitor = start_filesize_monitor(out_dir, prefix, metadata_filesize, stop_monitor)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                info = ydl2.extract_info(target_url, download=True)
        finally:
            stop_monitor.set()
            if monitor:
                monitor.join(timeout=1.0)

        final_path = None
        if info.get('requested_downloads'):
            final_path = info['requested_downloads'][0].get('filepath')
        if not final_path:
            candidates = files_matching_prefix(out_dir, prefix)
            if candidates:
                final_path = str(max(candidates, key=lambda p: p.stat().st_mtime))

        # Emit a final 100% progress event before done.
        emit(
            type='progress',
            percent=100,
            eta_seconds=0,
            speed_bps=0,
            downloaded_bytes=metadata_filesize or 0,
            total_bytes=metadata_filesize or 0,
        )
        emit(type='done', path=final_path or str(out_dir))
    except Exception as e:
        emit(type='error', message=f'{type(e).__name__}: {e}')
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())