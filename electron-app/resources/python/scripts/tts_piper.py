#!/usr/bin/env python3
"""
tts_piper.py — Local text-to-speech via Piper.

v1 scope:
  - TXT input file -> WAV output file
  - Uses the bundled Python venv's `piper` CLI
  - Uses voice models from resources/models/piper

Example:
  tts_piper.py input.txt --voice Ryan --out-dir ~/Desktop
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


VOICE_MAP = {
    "Ryan": "en_US-ryan-medium",
    "HFC Female": "en_US-hfc_female-medium",
    "Bryce": "en_US-bryce-medium",
}


def resources_root() -> Path:
    # electron-app/resources/python/scripts/tts_piper.py -> resources/
    return Path(__file__).resolve().parents[2]


def piper_bin() -> Path:
    """
    Locate Piper inside the bundled Python venv.

    Do not rely on sys.executable: uv-created venv python binaries may resolve
    through symlinks to ~/.local/share/uv/python/... rather than staying inside
    electron-app/resources/python/venv/bin.
    """
    root = resources_root()
    candidates = [
        root / "python" / "venv" / "bin" / "piper",
        Path(__file__).resolve().parents[1] / "venv" / "bin" / "piper",
    ]

    for candidate in candidates:
      if candidate.exists():
          return candidate

    raise FileNotFoundError(
        "Could not find bundled Piper CLI. Tried:\n"
        + "\n".join(str(p) for p in candidates)
        + "\nInstall with: uv pip install piper-tts --python electron-app/resources/python/venv/bin/python3"
    )


def voice_paths(voice_label: str) -> tuple[Path, Path]:
    model_name = VOICE_MAP[voice_label]
    model_dir = resources_root() / "models" / "piper"
    model = model_dir / f"{model_name}.onnx"
    config = model_dir / f"{model_name}.onnx.json"

    missing = [str(p) for p in (model, config) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing Piper voice file(s):\n"
            + "\n".join(missing)
            + "\nDownload/copy voice files into electron-app/resources/models/piper."
        )

    return model, config


def safe_output_name(stem: str) -> str:
    cleaned = stem.replace("/", "-").replace("\\", "-").strip()
    return cleaned or "speech"


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a text file to speech using Piper")
    parser.add_argument("input_txt", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--out", default="", help="Output filename, defaults to input stem + .wav")
    parser.add_argument("--voice", default="Ryan", choices=list(VOICE_MAP))
    parser.add_argument("--length-scale", type=float, default=1.0,
                        help="Piper phoneme length. Lower is faster; higher is slower.")
    parser.add_argument("--sentence-silence", type=float, default=0.2,
                        help="Seconds of silence after each sentence.")
    parser.add_argument("--volume", type=float, default=1.0,
                        help="Volume multiplier.")
    parser.add_argument("--speaker", type=int, default=0)
    args = parser.parse_args()

    input_path = args.input_txt.expanduser().resolve()
    if not input_path.is_file():
        print(f"ERROR: input text file not found: {input_path}", file=sys.stderr)
        return 1

    text = input_path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        print(f"ERROR: input text file is empty: {input_path}", file=sys.stderr)
        return 1

    out_dir = (args.out_dir.expanduser().resolve() if args.out_dir else input_path.parent)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.out:
        out_name = args.out
        if not out_name.lower().endswith(".wav"):
            out_name += ".wav"
    else:
        out_name = safe_output_name(input_path.stem) + ".wav"

    output_path = out_dir / out_name

    model, config = voice_paths(args.voice)
    piper = piper_bin()

    cmd = [
        str(piper),
        "--model", str(model),
        "--config", str(config),
        "--output_file", str(output_path),
        "--speaker", str(args.speaker),
        "--length_scale", str(args.length_scale),
        "--sentence_silence", str(args.sentence_silence),
        "--volume", str(args.volume),
    ]

    print(f"Voice: {args.voice}")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print("Synthesizing...")

    proc = subprocess.run(
        cmd,
        input=text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    if proc.returncode != 0:
        print(f"ERROR: Piper exited with status {proc.returncode}", file=sys.stderr)
        return proc.returncode

    print(f"Done: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
