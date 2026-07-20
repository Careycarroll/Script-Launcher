#!/usr/bin/env python3
"""Text to Audio wrapper for Heelworks.

Pipeline:
  TXT -> WAV via tts_piper.py -> optional ffmpeg transcode (mp3/m4a/mp4)

Keeps tts_piper.py focused on synthesis and lets this wrapper own format
handling, mirroring pdf_to_audio.py.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

VOICE_CHOICES = ("Ryan", "HFC Female", "Bryce")
FORMAT_CHOICES = ("wav", "mp3", "m4a", "mp4")
OUTPUT_PREFIXES = ("Done:", "Output:", "Wrote:", "Saved:", "Created:")


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def resource_root() -> Path:
    return script_dir().parents[1]


def tts_piper_path() -> Path:
    return script_dir() / "tts_piper.py"


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
        "ffmpeg is required for mp3/m4a/mp4 output but was not found. "
        "Install or bundle ffmpeg, or use --format wav."
    )


def available_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find available output path for {path}")


def run_checked(cmd: Sequence[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")
    return result


def clean_reported_path(line: str) -> str:
    cleaned = line.strip()
    for prefix in OUTPUT_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    return cleaned.strip('"')


def parse_first_output_path(stdout: str, fallback: Path) -> Path:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        candidate = Path(clean_reported_path(line)).expanduser()
        if candidate.exists():
            return candidate
    if lines:
        return Path(clean_reported_path(lines[-1])).expanduser()
    return fallback


def synthesize_wav(
    text_path: Path,
    wav_path: Path,
    voice: str,
    length_scale: str,
    sentence_silence: str,
    volume: str,
) -> Path:
    cmd = [
        sys.executable,
        str(tts_piper_path()),
        str(text_path),
        "--voice", voice,
        "--out-dir", str(wav_path.parent),
        "--out", wav_path.name,
        "--length-scale", length_scale,
        "--sentence-silence", sentence_silence,
        "--volume", volume,
    ]
    result = run_checked(cmd, "Piper synthesis")
    return parse_first_output_path(result.stdout, wav_path)


def ffmpeg_args(ffmpeg: str, wav_path: Path, output_path: Path, fmt: str, bitrate: int) -> list[str]:
    base = [ffmpeg, "-y", "-i", str(wav_path)]
    if fmt == "mp3":
        return base + ["-codec:a", "libmp3lame", "-b:a", f"{bitrate}k", str(output_path)]
    if fmt in {"m4a", "mp4"}:
        return base + ["-codec:a", "aac", "-b:a", f"{bitrate}k", str(output_path)]
    raise ValueError(f"Unsupported ffmpeg format: {fmt}")


def transcode_audio(wav_path: Path, output_path: Path, fmt: str, bitrate: int, ffmpeg: str | None) -> Path:
    ffmpeg_bin = find_ffmpeg(ffmpeg)
    cmd = ffmpeg_args(ffmpeg_bin, wav_path, output_path, fmt, bitrate)
    run_checked(cmd, f"ffmpeg {fmt} transcode")
    return output_path


def convert(args: argparse.Namespace) -> Path:
    text_path = Path(args.text).expanduser()
    if not text_path.exists():
        raise FileNotFoundError(f"Text file not found: {text_path}")
    if text_path.suffix.lower() != ".txt":
        raise ValueError(f"Expected a .txt file: {text_path}")

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else text_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    wav_path = available_path(out_dir / f"{text_path.stem}.wav")
    final_path = wav_path if args.format == "wav" else available_path(out_dir / f"{text_path.stem}.{args.format}")

    produced_wav = synthesize_wav(
        text_path, wav_path,
        args.voice, args.length_scale, args.sentence_silence, args.volume,
    )

    if args.format == "wav":
        return produced_wav

    produced_final = transcode_audio(produced_wav, final_path, args.format, args.bitrate, args.ffmpeg)
    if not args.keep_wav:
        try:
            produced_wav.unlink()
        except FileNotFoundError:
            pass
    return produced_final


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a text file to spoken audio with local Piper TTS.",
    )
    parser.add_argument("text", help="Text (.txt) file to convert")
    parser.add_argument("--voice", default="Ryan", choices=VOICE_CHOICES, help="Piper voice")
    parser.add_argument("--format", default="wav", choices=FORMAT_CHOICES, help="Output audio format")
    parser.add_argument("--bitrate", type=int, default=192, help="Bitrate in kbps for mp3/m4a/mp4")
    parser.add_argument("--out-dir", default="", help="Output directory; defaults beside the text file")
    parser.add_argument("--keep-wav", action="store_true", help="Keep intermediate WAV for non-WAV output")
    parser.add_argument("--length-scale", default="1.0", help="Lower = faster, higher = slower")
    parser.add_argument("--sentence-silence", default="0.2", help="Seconds of silence after each sentence")
    parser.add_argument("--volume", default="1.0", help="Volume multiplier")
    parser.add_argument("--ffmpeg", default="", help="Explicit ffmpeg binary path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = convert(args)
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
