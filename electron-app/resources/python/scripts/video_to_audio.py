#!/usr/bin/env python3
"""Video to Audio extraction for Heelworks.

Wraps ffmpeg to extract audio from a single video file. Supports mp3, m4a, and
wav, with optional EBU R128 loudness normalization. Batch/queue support is
tracked separately.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

FORMAT_CHOICES = ("mp3", "m4a", "wav")
NORMALIZE_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def resource_root() -> Path:
    # .../resources/python/scripts/video_to_audio.py -> .../resources
    return script_dir().parents[1]


def bundled_ffmpeg_path() -> Path:
    return resource_root() / "bin" / "ffmpeg"


def find_ffmpeg(explicit: str | None = None) -> str:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    bundled = bundled_ffmpeg_path()
    if bundled.exists():
        candidates.append(str(bundled))
    discovered = shutil.which("ffmpeg")
    if discovered:
        candidates.append(discovered)

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists() and path.is_file():
            return str(path)
        if shutil.which(candidate):
            return candidate

    raise RuntimeError(
        "ffmpeg is required but was not found. Install ffmpeg or bundle it "
        "under resources/bin/ffmpeg."
    )


def available_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find available output path for {path}")


def probe_source_audio(ffmpeg_bin: str, video: Path) -> dict[str, str]:
    """Return source audio stream info using ffprobe next to ffmpeg.

    Best-effort: on any failure, return an empty dict so callers can proceed.
    """
    ffprobe = str(Path(ffmpeg_bin).with_name("ffprobe"))
    if not Path(ffprobe).exists():
        discovered = shutil.which("ffprobe")
        if discovered:
            ffprobe = discovered
        else:
            return {}

    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,bit_rate,sample_rate,channels",
        "-of", "default=nw=1",
        str(video),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return {}
    if result.returncode != 0:
        return {}

    info: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    return info


def build_ffmpeg_args(
    ffmpeg: str,
    video: Path,
    output: Path,
    fmt: str,
    bitrate: int,
    normalize: bool,
) -> list[str]:
    args: list[str] = [ffmpeg, "-y", "-i", str(video), "-vn"]

    if normalize:
        args += ["-af", NORMALIZE_FILTER]

    if fmt == "mp3":
        args += ["-codec:a", "libmp3lame", "-b:a", f"{bitrate}k"]
    elif fmt == "m4a":
        args += ["-codec:a", "aac", "-b:a", f"{bitrate}k"]
    elif fmt == "wav":
        args += ["-codec:a", "pcm_s16le"]
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    args.append(str(output))
    return args


def run_ffmpeg(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def convert(
    video: Path,
    fmt: str,
    bitrate: int,
    normalize: bool,
    out_dir: Path | None,
    ffmpeg_bin: str,
) -> Path:
    if not video.exists():
        raise FileNotFoundError(f"Video not found: {video}")

    target_dir = out_dir.expanduser() if out_dir else video.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = available_path(target_dir / f"{video.stem}.{fmt}")

    source_info = probe_source_audio(ffmpeg_bin, video)
    if source_info:
        codec = source_info.get("codec_name", "?")
        sr = source_info.get("sample_rate", "?")
        ch = source_info.get("channels", "?")
        raw_br = source_info.get("bit_rate", "")
        try:
            src_kbps = int(raw_br) // 1000 if raw_br else None
        except ValueError:
            src_kbps = None
        br_display = f"{src_kbps} kbps" if src_kbps else "unknown kbps"
        print(f"Source audio: {codec} {br_display} @ {sr} Hz, {ch} ch", file=sys.stderr)
        if fmt != "wav" and src_kbps and bitrate > src_kbps:
            print(
                f"Note: selected {fmt} bitrate {bitrate} kbps exceeds source ({src_kbps} kbps); "
                f"no quality gain expected.",
                file=sys.stderr,
            )

    cmd = build_ffmpeg_args(ffmpeg_bin, video, output_path, fmt, bitrate, normalize)
    result = run_ffmpeg(cmd)

    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        raise RuntimeError(f"ffmpeg exited with code {result.returncode}")

    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract audio from a video using bundled or local ffmpeg.",
    )
    parser.add_argument("video", help="Video file to convert")
    parser.add_argument("--format", default="mp3", choices=FORMAT_CHOICES, help="Output audio format")
    parser.add_argument("--bitrate", type=int, default=192, help="Bitrate in kbps for mp3/m4a")
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Apply EBU R128 loudness normalization",
    )
    parser.add_argument("--out-dir", default="", help="Output directory; defaults to input file's folder")
    parser.add_argument("--ffmpeg", default="", help="Explicit ffmpeg binary path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    video = Path(args.video).expanduser()
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else None

    try:
        ffmpeg_bin = find_ffmpeg(args.ffmpeg or None)
        output = convert(
            video=video,
            fmt=args.format,
            bitrate=args.bitrate,
            normalize=args.normalize,
            out_dir=out_dir,
            ffmpeg_bin=ffmpeg_bin,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Done: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
