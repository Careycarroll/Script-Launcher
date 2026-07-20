#!/usr/bin/env python3
"""PDF to Audio workflow for Heelworks.

Pipeline:
  PDF -> TXT via docpipe.py pdf_to_txt -> WAV via tts_piper.py -> optional ffmpeg format

This script intentionally stays thin: document extraction remains in docpipe.py,
text-to-speech remains in tts_piper.py, and this file only orchestrates the
end-to-end workflow for Electron and direct CLI use.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence
import re

VOICE_CHOICES = ("Ryan", "HFC Female", "Bryce")
FORMAT_CHOICES = ("wav", "mp3", "m4a", "mp4")
OUTPUT_PREFIXES = ("Done:", "Output:", "Wrote:", "Saved:", "Created:")


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def resource_root() -> Path:
    # .../resources/python/scripts/pdf_to_audio.py -> .../resources
    return script_dir().parents[1]


def docpipe_path() -> Path:
    return script_dir() / "docpipe.py"


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
        # Allow PATH-resolved executable names passed explicitly.
        if shutil.which(candidate):
            return candidate

    raise RuntimeError(
        "ffmpeg is required for mp3/m4a/mp4 output but was not found. "
        "Install or bundle ffmpeg, or use --format wav."
    )


def available_path(path: Path) -> Path:
    """Return path if free; otherwise append _1, _2, ... before suffix."""
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
    """Strip common human-readable prefixes from scripts that print status lines."""
    cleaned = line.strip()
    for prefix in OUTPUT_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return cleaned.strip('"')


def parse_first_output_path(stdout: str, fallback: Path) -> Path:
    """Return the most likely output path from subprocess stdout.

    docpipe generally prints a bare path. tts_piper currently prints lines like
    "Done: /path/to/file.wav". ffmpeg needs the actual filesystem path, not the
    human-readable status prefix, so walk backward through stdout and strip known
    prefixes before falling back.
    """
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        candidate = Path(clean_reported_path(line)).expanduser()
        if candidate.exists():
            return candidate
    if lines:
        return Path(clean_reported_path(lines[-1])).expanduser()
    return fallback



def normalize_for_speech(text: str) -> str:
    """Collapse layout-mode line breaks into speech-friendly prose.

    - Rejoins hyphenated line breaks.
    - Turns single line breaks inside paragraphs into spaces.
    - Preserves blank-line paragraph breaks.
    - Collapses runs of whitespace.
    """
    # Join words split across lines with a hyphen: "strat-\negy" -> "strategy"
    text = re.sub(r"-\n(?=\w)", "", text)
    # Preserve paragraph breaks as a sentinel.
    text = re.sub(r"\n\s*\n+", "\uE000", text)
    # Any remaining single line breaks -> spaces.
    text = text.replace("\n", " ")
    # Restore paragraph breaks.
    text = text.replace("\uE000", "\n\n")
    # Squash runs of spaces.
    text = re.sub(r"[ \t]+", " ", text)
    # Trim per-paragraph leading/trailing spaces.
    text = "\n\n".join(seg.strip() for seg in text.split("\n\n"))
    return text.strip() + "\n"


def extract_text(pdf_path: Path, text_path: Path, layout: str) -> Path:
    cmd = [
        sys.executable,
        str(docpipe_path()),
        "pdf_to_txt",
        str(pdf_path),
        "--pdf_to_txt-layout",
        layout,
        "--out",
        str(text_path),
    ]
    result = run_checked(cmd, "PDF text extraction")
    return parse_first_output_path(result.stdout, text_path)


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
        "--voice",
        voice,
        "--out-dir",
        str(wav_path.parent),
        "--out",
        wav_path.name,
        "--length-scale",
        length_scale,
        "--sentence-silence",
        sentence_silence,
        "--volume",
        volume,
    ]
    result = run_checked(cmd, "Piper synthesis")
    return parse_first_output_path(result.stdout, wav_path)


def ffmpeg_args(ffmpeg: str, wav_path: Path, output_path: Path, fmt: str) -> list[str]:
    base = [ffmpeg, "-y", "-i", str(wav_path)]
    if fmt == "mp3":
        return base + ["-codec:a", "libmp3lame", "-b:a", "128k", str(output_path)]
    if fmt in {"m4a", "mp4"}:
        return base + ["-codec:a", "aac", "-b:a", "128k", str(output_path)]
    raise ValueError(f"Unsupported ffmpeg format: {fmt}")


def transcode_audio(wav_path: Path, output_path: Path, fmt: str, ffmpeg: str | None) -> Path:
    ffmpeg_bin = find_ffmpeg(ffmpeg)
    cmd = ffmpeg_args(ffmpeg_bin, wav_path, output_path, fmt)
    run_checked(cmd, f"ffmpeg {fmt} transcode")
    return output_path


def convert_one_pdf(args: argparse.Namespace, pdf_path: Path) -> Path:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file: {pdf_path}")

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else pdf_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    text_path = available_path(out_dir / f"{pdf_path.stem}.txt")
    wav_path = available_path(out_dir / f"{pdf_path.stem}.wav")
    final_path = wav_path if args.format == "wav" else available_path(out_dir / f"{pdf_path.stem}.{args.format}")

    produced_text = extract_text(pdf_path, text_path, args.layout)
    if not args.no_clean_text:
        try:
            cleaned = normalize_for_speech(produced_text.read_text(encoding="utf-8"))
            produced_text.write_text(cleaned, encoding="utf-8")
        except Exception as exc:
            print(f"WARN: text cleanup skipped: {exc}", file=sys.stderr)
    produced_wav = synthesize_wav(
        produced_text,
        wav_path,
        args.voice,
        args.length_scale,
        args.sentence_silence,
        args.volume,
    )

    if args.format == "wav":
        produced_final = produced_wav
    else:
        produced_final = transcode_audio(produced_wav, final_path, args.format, args.ffmpeg)
        if not args.keep_wav:
            try:
                produced_wav.unlink()
            except FileNotFoundError:
                pass

    if args.discard_text:
        try:
            produced_text.unlink()
        except FileNotFoundError:
            pass

    return produced_final


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract text from PDF files and convert it to spoken audio with local Piper TTS.",
    )
    parser.add_argument("pdfs", nargs="+", help="PDF file(s) to convert")
    parser.add_argument("--voice", default="Ryan", choices=VOICE_CHOICES, help="Piper voice to use")
    parser.add_argument("--layout", default="layout", choices=("layout", "plain"), help="PDF text extraction layout mode")
    parser.add_argument("--format", default="wav", choices=FORMAT_CHOICES, help="Output audio format")
    parser.add_argument("--out-dir", default="", help="Output directory; defaults beside each PDF")
    parser.add_argument("--no-clean-text", action="store_true", help="Skip speech-friendly text cleanup")
    parser.add_argument("--discard-text", action="store_true", help="Delete intermediate .txt after audio generation")
    parser.add_argument("--keep-wav", action="store_true", help="For non-WAV output, keep the intermediate WAV")
    parser.add_argument("--length-scale", default="1.0", help="Piper length scale; lower is faster, higher is slower")
    parser.add_argument("--sentence-silence", default="0.2", help="Seconds of silence after each sentence")
    parser.add_argument("--volume", default="1.0", help="Volume multiplier")
    parser.add_argument("--ffmpeg", default=None, help="Optional explicit ffmpeg path for mp3/m4a/mp4")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        for raw_pdf in args.pdfs:
            final_path = convert_one_pdf(args, Path(raw_pdf).expanduser())
            print(final_path)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
