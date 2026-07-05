#!/usr/bin/env python3
"""
ytdlp_download.py — Generic yt-dlp downloader for Heelworks Media domain.

Accepts any yt-dlp-supported URL. Emits line-delimited JSON on stdout:
  {"type":"info", "message":"..."}
  {"type":"metadata", "title":"...", "is_playlist": false, ...}
  {"type":"progress", "percent": N, ...}
  {"type":"conflict", "path":"...", "message":"..."}
  {"type":"done", "path":"..."}
  {"type":"error", "message":"..."}

Final #66 design:
  - Numeric prefix is optional for single videos.
  - Playlist downloads are opt-in and use one numbering system only:
      Playlist Folder/01. Title.ext, 02. Title.ext, ...
  - Playlist metadata preview is capped at 100 entries.
  - User may select playlist items; backend receives --playlist-items style ranges.
  - Captions, auto-captions, audio conversion, container/remux/recode,
    embedded thumbnails, cookies, retries, and concurrent fragments are exposed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import threading
import time
from pathlib import Path

import yt_dlp

ZEN_PROFILE = str(Path.home() / 'Library/Application Support/zen/Profiles/et1dknsr.Default (release)')
BROWSERS = {
    'none': None,
    'zen': f'firefox:{ZEN_PROFILE}',
    'firefox': 'firefox',
    'chrome': 'chrome',
    'safari': 'safari',
    'brave': 'brave',
    'edge': 'edge',
}

QUALITY_FORMATS = {
    'best': 'bestvideo+bestaudio/best',
    '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
    '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
    'audio': 'bestaudio/best',
}

NUM_PREFIX_RE = re.compile(r'^(\d+)\.\s')


def emit(**kwargs):
    sys.stdout.write(json.dumps(kwargs, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def read_action() -> dict:
    line = sys.stdin.readline().strip()
    if not line:
        return {'action': 'cancel'}
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {'action': 'cancel'}


def next_available_prefix(out_dir: Path) -> int:
    max_n = 0
    if not out_dir.exists():
        return 1
    for p in out_dir.iterdir():
        m = NUM_PREFIX_RE.match(p.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def files_matching_start(out_dir: Path, start: str) -> list[Path]:
    if not out_dir.exists() or not start:
        return []
    return [p for p in out_dir.iterdir() if p.name.startswith(start)]


def safe_title_for_template(title: str) -> str:
    cleaned = title.replace('/', '-').replace('\\', '-').strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    # Percent has special meaning in yt-dlp templates.
    return cleaned.replace('%', '%%') or 'download'


def safe_folder_name(title: str) -> str:
    cleaned = title.replace('/', '-').replace('\\', '-').strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned or 'playlist'


def apply_cookie_opts(ydl_opts: dict, browser: str):
    cookie_arg = BROWSERS.get(browser)
    if not cookie_arg:
        return
    if ':' in cookie_arg:
        browser_name, profile_path = cookie_arg.split(':', 1)
        ydl_opts['cookiesfrombrowser'] = (browser_name, profile_path, None, None)
    else:
        ydl_opts['cookiesfrombrowser'] = (cookie_arg, None, None, None)


def is_playlist_info(info: dict) -> bool:
    return info.get('_type') == 'playlist' or isinstance(info.get('entries'), list)


def playlist_entry_count(info: dict) -> int | None:
    entries = info.get('entries')
    if isinstance(entries, list):
        return len([e for e in entries if e])
    count = info.get('playlist_count') or info.get('n_entries')
    return int(count) if count else None


def playlist_preview_entries(info: dict, cap: int = 100) -> list[dict]:
    entries = info.get('entries') or []
    preview = []
    for i, entry in enumerate(entries[:cap], start=1):
        if not entry:
            continue
        idx = entry.get('playlist_index') or i
        preview.append({
            'index': idx,
            'title': entry.get('title') or entry.get('id') or f'Item {idx}',
            'duration_seconds': entry.get('duration'),
            'id': entry.get('id'),
        })
    return preview


def pick_metadata_format(info: dict, quality: str) -> dict | None:
    if is_playlist_info(info):
        entries = [e for e in (info.get('entries') or []) if e]
        if entries:
            info = entries[0]

    formats = info.get('formats') or []

    if quality == 'audio':
        audio = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
        if audio:
            return max(audio, key=lambda f: f.get('abr') or f.get('tbr') or 0)

    video = [
        f for f in formats
        if f.get('height') and f.get('width') and f.get('vcodec') != 'none'
    ]
    if not video:
        useful = [f for f in formats if f.get('filesize') or f.get('filesize_approx') or f.get('tbr')]
        return max(useful, key=lambda f: f.get('tbr') or 0) if useful else None

    def score(f):
        return (f.get('height') or 0, f.get('tbr') or 0)

    if quality == '720p':
        candidates = [f for f in video if (f.get('height') or 0) <= 720]
        return max(candidates or video, key=score)
    if quality == '1080p':
        candidates = [f for f in video if (f.get('height') or 0) <= 1080]
        return max(candidates or video, key=score)
    return max(video, key=score)


def estimate_filesize_bytes(fmt: dict | None, duration_seconds: float | None) -> int | None:
    if not fmt:
        return None
    size = fmt.get('filesize') or fmt.get('filesize_approx')
    if size:
        return int(size)
    tbr = fmt.get('tbr')
    if tbr and duration_seconds:
        return int((float(tbr) * 1000 / 8) * float(duration_seconds))
    return None


def monitored_bytes_for_start(out_dir: Path, filename_start: str) -> int:
    total = 0
    if not out_dir.exists():
        return 0
    for p in out_dir.iterdir():
        if not filename_start or p.name.startswith(filename_start):
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def start_filesize_monitor(out_dir: Path, filename_start: str, total_bytes: int | None, stop_event: threading.Event):
    if not total_bytes or total_bytes <= 0:
        return None

    def run():
        interval = 0.5
        alpha = 0.25
        last_time = time.time()
        last_bytes = 0
        max_bytes = 0
        ema_speed = 0.0

        while not stop_event.is_set():
            now = time.time()
            observed = monitored_bytes_for_start(out_dir, filename_start)
            max_bytes = max(max_bytes, observed)
            downloaded = min(max_bytes, total_bytes)
            elapsed = max(now - last_time, 0.001)
            delta = max(downloaded - last_bytes, 0)
            instant_speed = delta / elapsed
            if instant_speed > 0:
                ema_speed = instant_speed if ema_speed <= 0 else (alpha * instant_speed + (1 - alpha) * ema_speed)
            else:
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


def progress_hook(d):
    if d.get('status') == 'downloading':
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
    elif d.get('status') == 'finished':
        emit(type='info', message='Download complete, post-processing...')


def compact_indexes(indexes: list[int]) -> str:
    if not indexes:
        return ''
    xs = sorted(set(int(x) for x in indexes))
    ranges = []
    start = prev = xs[0]
    for x in xs[1:]:
        if x == prev + 1:
            prev = x
        else:
            ranges.append(f'{start}-{prev}' if start != prev else str(start))
            start = prev = x
    ranges.append(f'{start}-{prev}' if start != prev else str(start))
    return ','.join(ranges)


def build_postprocessors(args) -> list[dict]:
    postprocessors: list[dict] = []

    if args.quality == 'audio' and args.audio_format != 'original':
        postprocessors.append({
            'key': 'FFmpegExtractAudio',
            'preferredcodec': args.audio_format,
            'preferredquality': '0',
        })

    if args.container != 'auto' and args.quality != 'audio':
        if args.recode_video:
            postprocessors.append({
                'key': 'FFmpegVideoConvertor',
                'preferedformat': args.container,
            })
        else:
            postprocessors.append({
                'key': 'FFmpegVideoRemuxer',
                'preferedformat': args.container,
            })

    if args.embed_thumbnail:
        postprocessors.append({'key': 'EmbedThumbnail'})
        postprocessors.append({'key': 'FFmpegMetadata'})

    return postprocessors


def main() -> int:
    parser = argparse.ArgumentParser(description='Generic yt-dlp downloader')
    parser.add_argument('url')
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--use-prefix', action='store_true', default=False)
    parser.add_argument('--prefix', default='01')
    parser.add_argument('--quality', default='best', choices=list(QUALITY_FORMATS))
    parser.add_argument('--audio-format', default='original', choices=['original', 'mp3', 'm4a'])
    parser.add_argument('--captions', dest='captions', action='store_true', default=False)
    parser.add_argument('--no-captions', dest='captions', action='store_false')
    parser.add_argument('--auto-captions', dest='auto_captions', action='store_true', default=False)
    parser.add_argument('--no-auto-captions', dest='auto_captions', action='store_false')
    parser.add_argument('--sub-langs', default='en')
    parser.add_argument('--embed-subs', dest='embed_subs', action='store_true', default=False)
    parser.add_argument('--no-embed-subs', dest='embed_subs', action='store_false')
    parser.add_argument('--browser', default='none', choices=list(BROWSERS))
    parser.add_argument('--allow-playlist', action='store_true', default=False)
    parser.add_argument('--playlist-items', default='')
    parser.add_argument('--container', default='auto', choices=['auto', 'mkv', 'mp4', 'webm'])
    parser.add_argument('--recode-video', action='store_true', default=False)
    parser.add_argument('--embed-thumbnail', action='store_true', default=False)
    parser.add_argument('--concurrent-fragments', type=int, default=4)
    parser.add_argument('--retries', type=int, default=10)
    parser.add_argument('--fragment-retries', type=int, default=10)
    args = parser.parse_args()

    out_dir = args.out_dir.expanduser().resolve()
    if not out_dir.is_dir():
        emit(type='error', message=f'not a directory: {out_dir}')
        return 1

    ydl_opts = {
        'format': QUALITY_FORMATS[args.quality],
        'concurrent_fragment_downloads': args.concurrent_fragments,
        'retries': args.retries,
        'fragment_retries': args.fragment_retries,
        'progress_hooks': [progress_hook],
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': False,
        # Do not suppress playlists during metadata probe; we need to detect them.
    }
    apply_cookie_opts(ydl_opts, args.browser)

    if args.captions or args.auto_captions:
        ydl_opts['subtitleslangs'] = [s.strip() for s in args.sub_langs.split(',') if s.strip()] or ['en']
        ydl_opts['subtitlesformat'] = 'vtt'
        if args.captions:
            ydl_opts['writesubtitles'] = True
        if args.auto_captions:
            ydl_opts['writeautomaticsub'] = True
        if args.embed_subs:
            ydl_opts['embedsubtitles'] = True
            if args.container == 'auto':
                ydl_opts['merge_output_format'] = 'mp4'
            ydl_opts.setdefault('postprocessors', []).append(
                {'key': 'FFmpegEmbedSubtitle', 'already_have_subtitle': False}
            )

    postprocessors = build_postprocessors(args)
    if postprocessors:
        ydl_opts.setdefault('postprocessors', []).extend(postprocessors)

    emit(type='info', message='Fetching media metadata...')
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            probe = ydl.extract_info(args.url, download=False)
    except Exception as e:
        emit(type='error', message=f'{type(e).__name__}: {e}')
        return 1

    playlist = is_playlist_info(probe)
    count = playlist_entry_count(probe) if playlist else None
    selected = pick_metadata_format(probe, args.quality)
    original_title = probe.get('title', '') or 'download'
    duration_seconds = probe.get('duration')
    metadata_filesize = estimate_filesize_bytes(selected, duration_seconds)

    emit(
        type='metadata',
        title=original_title,
        is_playlist=playlist,
        playlist_count=count,
        playlist_preview=playlist_preview_entries(probe, 100) if playlist else [],
        playlist_preview_cap=100,
        width=selected.get('width') if selected else None,
        height=selected.get('height') if selected else None,
        filesize=metadata_filesize,
        duration_seconds=duration_seconds,
        format_id=selected.get('format_id') if selected else None,
        fps=selected.get('fps') if selected else None,
        ext=selected.get('ext') if selected else None,
    )

    confirm_msg = read_action()
    if confirm_msg.get('action') != 'confirm':
        emit(type='error', message='cancelled by user')
        return 1

    allow_playlist = bool(confirm_msg.get('allow_playlist', args.allow_playlist))
    selected_playlist_items = confirm_msg.get('playlist_items') or args.playlist_items

    if playlist and not allow_playlist:
        emit(type='error', message='playlist detected but playlist downloads are not enabled')
        return 1

    if playlist:
        playlist_folder = safe_folder_name(confirm_msg.get('title') or original_title)
        playlist_dir = out_dir / playlist_folder
        if playlist_dir.exists() and not playlist_dir.is_dir():
            emit(type='error', message=f'playlist output path exists and is not a folder: {playlist_dir}')
            return 1
        playlist_dir.mkdir(exist_ok=True)
        ydl_opts['outtmpl'] = str(playlist_dir / '%(playlist_index)02d. %(title)s.%(ext)s')
        ydl_opts['noplaylist'] = False
        if selected_playlist_items:
            ydl_opts['playlist_items'] = selected_playlist_items
        monitor_dir = playlist_dir
        monitor_start = ''
    else:
        ydl_opts['noplaylist'] = True
        edited_title = safe_title_for_template((confirm_msg.get('title') or original_title).strip())
        if args.use_prefix:
            prefix = args.prefix
            existing = files_matching_start(out_dir, f'{prefix}. ')
            if existing:
                emit(
                    type='conflict',
                    path=str(existing[0]),
                    message=f'{len(existing)} file(s) already start with "{prefix}. "',
                )
                action = read_action().get('action', 'cancel')
                if action == 'cancel':
                    emit(type='error', message='cancelled by user')
                    return 1
                if action == 'overwrite':
                    for p in existing:
                        try:
                            if p.is_dir():
                                shutil.rmtree(p)
                            else:
                                p.unlink()
                            emit(type='info', message=f'Deleted: {p.name}')
                        except OSError as e:
                            emit(type='error', message=f'could not delete {p.name}: {e}')
                            return 1
                elif action == 'increment':
                    prefix = f'{next_available_prefix(out_dir):02d}'
                    emit(type='info', message=f'Using prefix {prefix} instead')
            ydl_opts['outtmpl'] = str(out_dir / f'{prefix}. {edited_title}.%(ext)s')
            monitor_start = f'{prefix}. '
        else:
            existing = files_matching_start(out_dir, f'{edited_title}.')
            if existing:
                emit(
                    type='conflict',
                    path=str(existing[0]),
                    message=f'file already exists for title "{edited_title}"',
                )
                action = read_action().get('action', 'cancel')
                if action == 'cancel':
                    emit(type='error', message='cancelled by user')
                    return 1
                if action == 'overwrite':
                    for p in existing:
                        try:
                            if p.is_dir():
                                shutil.rmtree(p)
                            else:
                                p.unlink()
                            emit(type='info', message=f'Deleted: {p.name}')
                        except OSError as e:
                            emit(type='error', message=f'could not delete {p.name}: {e}')
                            return 1
                elif action == 'increment':
                    # Increment has no meaning without prefix; switch to prefix mode.
                    prefix = f'{next_available_prefix(out_dir):02d}'
                    ydl_opts['outtmpl'] = str(out_dir / f'{prefix}. {edited_title}.%(ext)s')
                    monitor_start = f'{prefix}. '
                    emit(type='info', message=f'Using prefix {prefix} instead')
                else:
                    ydl_opts['outtmpl'] = str(out_dir / f'{edited_title}.%(ext)s')
                    monitor_start = f'{edited_title}.'
            else:
                ydl_opts['outtmpl'] = str(out_dir / f'{edited_title}.%(ext)s')
                monitor_start = f'{edited_title}.'
        monitor_dir = out_dir

    emit(type='info', message='Starting download...')
    emit(
        type='progress',
        percent=0,
        eta_seconds=0,
        speed_bps=0,
        downloaded_bytes=0,
        total_bytes=metadata_filesize or 0,
    )

    stop_monitor = threading.Event()
    monitor = start_filesize_monitor(monitor_dir, monitor_start, metadata_filesize, stop_monitor)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(args.url, download=True)
    except Exception as e:
        emit(type='error', message=f'{type(e).__name__}: {e}')
        return 1
    finally:
        stop_monitor.set()
        if monitor:
            monitor.join(timeout=1.0)

    final_path = None
    if playlist:
        final_path = str(monitor_dir)
    elif info and info.get('requested_downloads'):
        final_path = info['requested_downloads'][0].get('filepath')
    if not final_path:
        candidates = files_matching_start(monitor_dir, monitor_start)
        if candidates:
            final_path = str(max(candidates, key=lambda p: p.stat().st_mtime))

    emit(
        type='progress',
        percent=100,
        eta_seconds=0,
        speed_bps=0,
        downloaded_bytes=metadata_filesize or 0,
        total_bytes=metadata_filesize or 0,
    )
    emit(type='done', path=final_path or str(out_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
