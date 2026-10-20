#!/usr/bin/env python3
"""
say_frontend.py — the part of macOS `say` that Piper is missing.

Piper's frontend is espeak-ng phonemization. That handles graphemes, numbers,
currency and percent signs perfectly well. What it has no concept of is
*structure*: hand Piper a paragraph and it synthesizes the whole thing as one
prosodic unit, so intonation drifts flat and there is no pause anywhere the
author intended one.

This module supplies the three things `say` does for free and Piper does not:

  1. Sentence-boundary segmentation. Chunks are built out of whole sentences,
     never cut mid-clause, so Piper plans prosody per sentence and intonation
     resets at each boundary. This is the single biggest factor in "flow".

  2. Real silence at paragraph and section breaks, concatenated in as audio.
     Piper will not produce it on its own. `--sentence-silence` only applies
     within one invocation and cannot distinguish a paragraph break from a
     sentence break.

  3. All-caps and initialism repair. espeak-ng reads short all-caps tokens
     letter by letter, so a heading like THE FEAR FACTOR becomes
     "tee aitch ee ...". Headings are also usually unpunctuated, which makes
     them run into the following sentence.

Deliberately NOT included: aggressive number/currency expansion. espeak-ng
already does that correctly, and doing it twice on pre-normalized text is
wasted effort and a source of bugs.

Zero dependencies beyond the standard library. No ffmpeg — silence is written
as zero-valued frames with the `wave` module, and optional m4a encoding uses
`afconvert`, which ships with macOS. That keeps it compatible with ADR-0004
(static binaries in resources/bin, Python as orchestration only).


Use as a library (the intended path for tts_piper.py)
-----------------------------------------------------
    from say_frontend import plan

    for kind, payload in plan(text):
        if kind == "speak":
            piper_synthesize(payload, out_wav)   # your existing call
        else:
            append_silence(payload)              # payload is milliseconds

Or hand the whole job over:

    from say_frontend import render
    render(text, model="/path/en_US-ryan-high.onnx", out="case.m4a")


Use standalone
--------------
    ./say_frontend.py case.txt --model ~/voices/en_US-ryan-high.onnx
    ./say_frontend.py case.txt --dry-run          # show the split, synth nothing
    ./say_frontend.py case.txt --model M --jobs 4 --format wav
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

__all__ = ["normalize", "sentences", "plan", "render", "PIPER"]

# Override if the binary lives somewhere else, e.g. resources/bin/piper.
PIPER = os.environ.get("PIPER_BIN", "piper")


# ─────────────────────────── Light normalization ───────────────────────────
#
# Everything here is something espeak-ng gets wrong. Nothing here duplicates
# what it already gets right.

# Read as words, not as letters. Longest first where they overlap.
_ABBREV = [
    (r"\bHUD-1\b", "HUD one"),
    (r"\bHUD-I\b", "HUD one"),          # common OCR corruption of HUD-1
    (r"\bU\.S\.A\.", "USA"),
    (r"\bU\.S\.\s", "United States "),
    (r"\bU\.K\.\s", "United Kingdom "),
    (r"\be\.g\.,?", "for example,"),
    (r"\bi\.e\.,?", "that is,"),
    (r"\betc\.", "and so on."),
    (r"\bvs\.", "versus"),
    (r"\bapprox\.", "approximately"),
    (r"\bNo\.\s*(\d)", r"number \1"),
]

# Acronyms that should stay letter-by-letter. espeak already spells unknown
# all-caps tokens, so these are listed only to protect them from the
# heading-detection pass below.
_KEEP_CAPS = {
    "FHA", "HUD", "SEC", "OSHA", "FCIC", "GSE", "GSES", "QA", "QC", "CEO",
    "CFO", "COO", "VP", "HR", "IP", "MBWA", "ROTC", "SIFI", "LP", "USA",
    "FICO", "MBA", "HBR", "R&D",
}

# A heading looks like: a whole line, mostly capitals, no terminal punctuation,
# and short enough that it cannot be a sentence.
_HEADING_MAX_WORDS = 9


def _fix_heading(line: str) -> str:
    """THE FEAR FACTOR -> The Fear Factor.

    Two problems solved at once. espeak-ng reads short all-caps tokens as
    initialisms, and an unpunctuated heading gets glued to the sentence after
    it by any punctuation-based splitter. Title case fixes the first, the
    added period fixes the second and buys a natural pause.
    """
    stripped = line.strip()
    if not stripped:
        return line

    words = stripped.split()
    if len(words) > _HEADING_MAX_WORDS:
        return line
    if stripped[-1] in ".!?:;,":
        return line

    # Must be predominantly capitals, ignoring the small connecting words.
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return line
    if sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return line

    out = []
    for w in words:
        core = w.strip(".,;:!?'\"()")
        if core in _KEEP_CAPS:
            out.append(w)                       # leave FHA, HUD, SEC alone
        elif len(core) <= 3 and w.isupper() and core not in _KEEP_CAPS:
            # Short words like THE, AND, OF, A -> lowercase-ish title form.
            out.append(w.capitalize())
        else:
            out.append(w.capitalize() if w.isupper() else w)
    return " ".join(out) + "."


def normalize(text: str, fix_headings: bool = True) -> str:
    # Rejoin words split across a line by a hyphen. The most common artifact
    # in PDF-extracted text, and it breaks both segmentation and phonemization.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Typographic characters espeak either skips or mispronounces.
    text = (text.replace("\u2019", "'").replace("\u2018", "'")
                .replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u2014", ", ").replace("\u2013", "-")
                .replace("\u2026", ".").replace("\u00a0", " "))

    for pattern, repl in _ABBREV:
        text = re.sub(pattern, repl, text)

    if fix_headings:
        text = "\n".join(_fix_heading(l) for l in text.split("\n"))

    # Collapse horizontal whitespace; preserve blank lines, which are the
    # only paragraph-break signal we have.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─────────────────────────── Segmentation ───────────────────────────

# Do not split after these, despite the period.
_NO_SPLIT = (r"(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bProf)(?<!\bSt)"
             r"(?<!\bJr)(?<!\bSr)(?<!\bInc)(?<!\bLtd)(?<!\bCo)(?<!\bCorp)"
             r"(?<!\bvs)(?<!\bNo)(?<![A-Z])")
_SPLIT = re.compile(_NO_SPLIT + r"(?<=[.!?])[\"')\]]*\s+")


def sentences(paragraph: str) -> list[str]:
    """Split a paragraph into sentences, collapsing internal newlines."""
    flat = re.sub(r"\s*\n\s*", " ", paragraph).strip()
    return [s.strip() for s in _SPLIT.split(flat) if s.strip()]


def plan(text: str,
         max_chars: int = 600,
         pause_ms: int = 700,
         sentence_pause_ms: int = 0,
         normalize_text: bool = True) -> list[tuple[str, object]]:
    """Turn text into a flat list of ('speak', str) and ('silence', ms) items.

    Chunks are groups of whole sentences totalling at most max_chars. A single
    sentence longer than max_chars is emitted whole rather than cut — a long
    chunk sounds better than a severed clause.

    This is the function tts_piper.py should call.
    """
    if normalize_text:
        text = normalize(text)

    items: list[tuple[str, object]] = []
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]

    for i, para in enumerate(paragraphs):
        buf: list[str] = []
        length = 0
        for sent in sentences(para):
            if buf and length + len(sent) + 1 > max_chars:
                items.append(("speak", " ".join(buf)))
                if sentence_pause_ms:
                    items.append(("silence", sentence_pause_ms))
                buf, length = [], 0
            buf.append(sent)
            length += len(sent) + 1
        if buf:
            items.append(("speak", " ".join(buf)))
        if pause_ms and i < len(paragraphs) - 1:
            items.append(("silence", pause_ms))

    return items


# ─────────────────────────── Piper + audio ───────────────────────────

def _piper(chunk: str, model: str, out_wav: Path,
           length_scale: float | None = None) -> None:
    cmd = [PIPER, "--model", str(Path(model).expanduser()),
           "--output_file", str(out_wav)]
    if length_scale is not None:
        cmd += ["--length_scale", str(length_scale)]
    subprocess.run(cmd, input=chunk.encode("utf-8"),
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                   check=True)


def _wav_params(path: Path):
    with wave.open(str(path), "rb") as w:
        return w.getparams()


def _write_silence(path: Path, ms: int, params) -> None:
    """Silence as zero frames at the model's own sample rate. No resampling,
    so no clicks at the joins — the usual cause of crackle when ffmpeg
    concatenates files whose rates disagree."""
    frames = int(params.framerate * ms / 1000)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        w.writeframes(b"\x00" * frames * params.nchannels * params.sampwidth)


def _concat(parts: list[Path], out: Path) -> None:
    params = _wav_params(parts[0])
    with wave.open(str(out), "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        for p in parts:
            with wave.open(str(p), "rb") as r:
                if r.getframerate() != params.framerate:
                    raise RuntimeError(f"sample rate mismatch in {p.name}")
                w.writeframes(r.readframes(r.getnframes()))


def _to_m4a(wav: Path, out: Path, quality: int = 90) -> None:
    """afconvert ships with macOS, so no ffmpeg dependency."""
    if not shutil.which("afconvert"):
        raise RuntimeError("afconvert not found; use --format wav")
    subprocess.run(["afconvert", "-f", "m4af", "-d", "aac",
                    "-q", str(quality), "-c", "1", str(wav), str(out)],
                   check=True, stdout=subprocess.DEVNULL)


def render(text: str, model: str, out: str | Path,
           max_chars: int = 600, pause_ms: int = 700,
           sentence_pause_ms: int = 0, length_scale: float | None = None,
           jobs: int = 1, keep_chunks: bool = False) -> Path:
    """Full pipeline: plan, synthesize, concatenate, encode."""
    out = Path(out).expanduser()
    items = plan(text, max_chars, pause_ms, sentence_pause_ms)
    speak = [(i, p) for i, (k, p) in enumerate(items) if k == "speak"]

    tmp = Path(tempfile.mkdtemp(prefix="say_frontend_"))
    try:
        wavs: dict[int, Path] = {}

        def work(item):
            idx, chunk = item
            path = tmp / f"{idx:05d}.wav"
            _piper(chunk, model, path, length_scale)
            return idx, path

        if jobs > 1:
            with concurrent.futures.ThreadPoolExecutor(jobs) as ex:
                for idx, path in ex.map(work, speak):
                    wavs[idx] = path
        else:
            for item in speak:
                idx, path = work(item)
                wavs[idx] = path
                print(f"  {len(wavs)}/{len(speak)}", end="\r", file=sys.stderr)

        params = _wav_params(next(iter(wavs.values())))

        parts: list[Path] = []
        for i, (kind, payload) in enumerate(items):
            if kind == "speak":
                parts.append(wavs[i])
            else:
                sil = tmp / f"{i:05d}_sil.wav"
                _write_silence(sil, int(payload), params)
                parts.append(sil)

        joined = tmp / "joined.wav"
        _concat(parts, joined)

        if out.suffix.lower() in (".m4a", ".m4b"):
            _to_m4a(joined, out)
        else:
            shutil.copy(joined, out)
        return out
    finally:
        if keep_chunks:
            print(f"chunks kept in {tmp}", file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────── CLI ───────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("input")
    ap.add_argument("--model", help="path to a Piper .onnx voice")
    ap.add_argument("--out")
    ap.add_argument("--format", choices=["m4a", "wav"], default="m4a")
    ap.add_argument("--chunk", type=int, default=600,
                    help="max characters per chunk, sentence-aligned")
    ap.add_argument("--pause", type=int, default=700,
                    help="ms of silence at each blank line")
    ap.add_argument("--sentence-pause", type=int, default=0)
    ap.add_argument("--length-scale", type=float, default=None,
                    help="Piper speed; lower is faster")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--keep-chunks", action="store_true")
    ap.add_argument("--no-normalize", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the segmentation and exit")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    text = src.read_text(encoding="utf-8", errors="replace")

    items = plan(text, args.chunk, args.pause, args.sentence_pause,
                 normalize_text=not args.no_normalize)

    if args.dry_run:
        spoken = 0
        for kind, payload in items:
            if kind == "speak":
                spoken += 1
                print(f"\n── chunk {spoken}  ({len(payload)} chars) "
                      f"{'─' * 30}\n{payload}")
            else:
                print(f"\n[silence {payload} ms]")
        words = sum(len(p.split()) for k, p in items if k == "speak")
        print(f"\n{spoken} chunks, {words} words, "
              f"{sum(p for k, p in items if k == 'silence')/1000:.0f}s silence",
              file=sys.stderr)
        return 0

    if not args.model:
        ap.error("--model is required unless --dry-run")

    out = Path(args.out).expanduser() if args.out else \
        src.with_suffix("." + args.format)
    print(f"{sum(1 for k, _ in items if k == 'speak')} chunks -> {out}",
          file=sys.stderr)
    render(text, args.model, out, args.chunk, args.pause, args.sentence_pause,
           args.length_scale, args.jobs, args.keep_chunks)
    print(f"\n{out}  {out.stat().st_size / 1_048_576:.1f} MB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
