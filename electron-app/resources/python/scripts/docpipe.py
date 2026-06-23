#!/usr/bin/env python3
"""
docpipe — Unified document conversion pipeline.

Single entry point for all document conversions. Stages are registered in
STAGES; edges in EDGES define the conversion graph. The router finds a path
from --from to --to via BFS and runs each stage in order.

Add a new stage:
  1. Write a function: stage_<from>_to_<to>(input_path, options, workdir) -> Path
  2. Register it in STAGES with its options schema
  3. Add an entry to EDGES

The CLI auto-discovers everything from STAGES/EDGES — no other code changes.

Batching:
  Stages declare an arity via Stage.multi_input.
    False (default) — 1 input → 1 output. Multiple inputs on the CLI are looped.
    True            — N inputs → 1 output. The stage receives the full list.
                      --out is REQUIRED for multi_input stages.

Directory inputs are expanded in-place to their sorted contents, filtered to
formats the first stage's source format declares as recognized extensions.
Individual files are also validated against the format's extensions — defense
at the boundary so stages never see inputs they cannot handle.

CLI:
  docpipe --from pdf --to txt input.pdf
  docpipe --from pdf --to txt a.pdf b.pdf c.pdf       # batch: N→N
  docpipe --from pdf --to txt input.pdf --pdf-layout plain
  docpipe --from images --to pdf img1.png img2.png --out combined.pdf
  docpipe --from images --to pdf ~/scans/ --out scans.pdf
  docpipe --from pptx --to pdf deck.pptx              # macOS + PowerPoint
  docpipe --from pptx --to pdf deck.pptx --pptx-compress medium
  docpipe --no-keep-intermediate ...     # delete intermediates (default: keep)
  docpipe --force                        # overwrite existing outputs
  docpipe --dry-run                      # print resolved chain, do not execute
  docpipe --introspect                   # print graph + options as JSON
"""

from __future__ import annotations

import argparse
import atexit
import io
import json
import platform
import subprocess
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import zlib

import pikepdf
import pymupdf  # PyMuPDF >= 1.24
from PIL import Image


# ─── Types ────────────────────────────────────────────────────────────────────

StageFn = Callable[[Path, dict, Path], Path]
MultiStageFn = Callable[[list[Path], dict, Path], Path]


@dataclass
class StageOption:
    name: str           # CLI flag suffix, e.g. "layout" -> --pdf-layout
    choices: list[str]
    default: str
    help: str = ""


@dataclass
class Stage:
    src: str            # source format, e.g. "pdf"
    dst: str            # destination format, e.g. "txt"
    fn: StageFn | MultiStageFn
    options: list[StageOption] = field(default_factory=list)
    multi_input: bool = False  # True = N inputs → 1 output (e.g. images→pdf)

    @property
    def name(self) -> str:
        return f"{self.src}_to_{self.dst}"

    @property
    def flag_prefix(self) -> str:
        return f"--{self.src}"


# ─── Format → recognized extensions ───────────────────────────────────────────

FORMAT_EXTENSIONS: dict[str, set[str]] = {
    "pdf":    {".pdf"},
    "txt":    {".txt"},
    "md":     {".md", ".markdown"},
    "images": {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"},
    "pptx":   {".pptx"},
    "docx":   {".docx"},
}


# ─── Layout reconstruction (for pdf → txt layout mode) ────────────────────────

# Tuned for typical 10–12pt body text on US Letter / A4.
# These constants are the only knobs that affect column alignment fidelity.
_CHAR_WIDTH_PT = 6.0   # approx point-width of one monospace char
_ROW_TOL_PT    = 3.0   # vertical tolerance for grouping blocks into a row


def _layout_page_text(page) -> str:
    """
    Reconstruct text with column/table alignment by binning blocks into rows
    on y-coordinate, then padding each row with spaces based on x-position.
    Closest approximation to pdftotext -layout we can do via pymupdf blocks.
    """
    blocks = page.get_text("blocks")
    # Each block: (x0, y0, x1, y1, text, block_no, block_type)
    # block_type == 0 means text; skip image blocks.
    lines: list[tuple[float, float, float, float, str]] = []

    for b in blocks:
        if len(b) < 7 or b[6] != 0:
            continue
        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
        text = text.rstrip("\n")
        if not text.strip():
            continue
        # Split multi-line blocks into individual lines, each inheriting the
        # block's x0 but synthesizing y by linear interpolation.
        block_lines = text.split("\n")
        n = len(block_lines)
        if n == 1:
            lines.append((x0, y0, x1, y1, block_lines[0]))
        else:
            line_h = (y1 - y0) / n
            for i, lt in enumerate(block_lines):
                if not lt.strip():
                    continue
                ly0 = y0 + i * line_h
                ly1 = ly0 + line_h
                lines.append((x0, ly0, x1, ly1, lt))

    if not lines:
        return ""

    # Normalize x: subtract leftmost x0 so output starts at column 0.
    # Prevents universal leading-whitespace from PDF page margins.
    min_x = min(l[0] for l in lines)
    if min_x > 0:
        lines = [(x0 - min_x, y0, x1, y1, t) for (x0, y0, x1, y1, t) in lines]

    # Sort by y (top → bottom), then x (left → right) as tiebreaker
    lines.sort(key=lambda l: (l[1], l[0]))

    # Bin into rows: consecutive lines within _ROW_TOL_PT of each other
    # share a row. This is what reconstructs columnar layouts.
    rows: list[list[tuple[float, float, float, float, str]]] = []
    current_row: list = []
    row_y: float | None = None
    for l in lines:
        if row_y is None or (l[1] - row_y) <= _ROW_TOL_PT:
            current_row.append(l)
            row_y = l[1] if row_y is None else min(row_y, l[1])
        else:
            rows.append(current_row)
            current_row = [l]
            row_y = l[1]
    if current_row:
        rows.append(current_row)

    # Emit each row with x-position-based padding
    out: list[str] = []
    for row in rows:
        row.sort(key=lambda l: l[0])
        buf = ""
        for x0, _y0, _x1, _y1, text in row:
            col = int(x0 / _CHAR_WIDTH_PT)
            if col > len(buf):
                buf += " " * (col - len(buf))
            elif buf and not buf.endswith(" "):
                buf += " "
            buf += text.rstrip()
        out.append(buf.rstrip())

    return "\n".join(out)


# ─── Stage: pdf → txt ─────────────────────────────────────────────────────────

def stage_pdf_to_txt(input_path: Path, opts: dict, workdir: Path) -> Path:
    """Extract text from a PDF. Options: layout (default) or plain."""
    mode = opts.get("layout", "layout")
    output_path = workdir  # runner passes the resolved output path

    doc = pymupdf.open(input_path)
    try:
        chunks: list[str] = []
        for page in doc:
            if mode == "layout":
                text = _layout_page_text(page)
            else:
                text = page.get_text("text")
            chunks.append(text)
        output_path.write_text("\n".join(chunks), encoding="utf-8")
    finally:
        doc.close()

    return output_path


# ─── Stage: images → pdf ──────────────────────────────────────────────────────

_PAGE_SIZES_PT: dict[str, tuple[float, float]] = {
    "letter": (612.0, 792.0),
    "a4":     (595.0, 842.0),
}


def stage_images_to_pdf(inputs: list[Path], opts: dict, workdir: Path) -> Path:
    """Combine images into a single PDF. Multi-input: N images → 1 PDF."""
    page_size = opts.get("page_size", "auto")
    output_path = workdir  # workdir is the resolved output path for multi_input

    out_doc = pymupdf.open()
    try:
        for img_path in inputs:
            img_doc = pymupdf.open(img_path)
            try:
                pdf_bytes = img_doc.convert_to_pdf()
            finally:
                img_doc.close()

            img_pdf = pymupdf.open("pdf", pdf_bytes)
            try:
                img_page = img_pdf[0]
                img_w, img_h = img_page.rect.width, img_page.rect.height

                if page_size == "auto":
                    pw, ph = img_w, img_h
                else:
                    pw, ph = _PAGE_SIZES_PT[page_size]
                    # Auto-orient: landscape image → landscape page
                    if (img_w > img_h) != (pw > ph):
                        pw, ph = ph, pw

                new_page = out_doc.new_page(width=pw, height=ph)

                if page_size == "auto":
                    new_page.show_pdf_page(new_page.rect, img_pdf, 0)
                else:
                    # contain-fit: scale to fit, center
                    scale = min(pw / img_w, ph / img_h)
                    fitted_w = img_w * scale
                    fitted_h = img_h * scale
                    x0 = (pw - fitted_w) / 2
                    y0 = (ph - fitted_h) / 2
                    target = pymupdf.Rect(x0, y0, x0 + fitted_w, y0 + fitted_h)
                    new_page.show_pdf_page(target, img_pdf, 0)
            finally:
                img_pdf.close()

        out_doc.save(output_path, garbage=4, deflate=True)
    finally:
        out_doc.close()

    return output_path


# ─── Stage: pptx → pdf (macOS, via PowerPoint AppleScript) ────────────────────

_PPTX_LAUNCHED_BY_US = False  # Module-level flag for batch quit-after logic


def _powerpoint_is_running() -> bool:
    """Returns True if Microsoft PowerPoint is currently running."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "Microsoft PowerPoint"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _quit_powerpoint_if_we_launched_it():
    """atexit hook: quit PowerPoint if WE launched it during this batch."""
    global _PPTX_LAUNCHED_BY_US
    if _PPTX_LAUNCHED_BY_US:
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "Microsoft PowerPoint" to quit'],
                capture_output=True, timeout=10,
            )
            print("🔴 PowerPoint closed", file=sys.stderr)
        except Exception:
            pass


atexit.register(_quit_powerpoint_if_we_launched_it)


# DPI presets — match historical ghostscript /screen, /ebook, /printer levels
_DPI_PRESETS: dict[str, int | None] = {
    "none":   None,   # no downsampling, raw PowerPoint output
    "small":  72,     # screen viewing only
    "medium": 150,    # balanced (default)
    "large":  300,    # print quality
}


def _parse_content_stream_ctms(page) -> dict[str, tuple[float, float]]:
    """Walk content stream, track CTM, return {image_name: (w_pt, h_pt)}."""
    try:
        instructions = list(pikepdf.parse_content_stream(page))
    except Exception:
        return {}

    result: dict[str, tuple[float, float]] = {}
    ctm_stack: list[list[float]] = [[1, 0, 0, 1, 0, 0]]

    def mul(m1, m2):
        a1, b1, c1, d1, e1, f1 = m1
        a2, b2, c2, d2, e2, f2 = m2
        return [
            a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2,
        ]

    for inst in instructions:
        op = str(inst.operator)
        operands = inst.operands
        if op == "q":
            ctm_stack.append(list(ctm_stack[-1]))
        elif op == "Q":
            if len(ctm_stack) > 1:
                ctm_stack.pop()
        elif op == "cm" and len(operands) == 6:
            m = [float(x) for x in operands]
            ctm_stack[-1] = mul(m, ctm_stack[-1])
        elif op == "Do" and operands:
            name = str(operands[0])
            ctm = ctm_stack[-1]
            result[name] = (abs(ctm[0]), abs(ctm[3]))
    return result


def _downsample_one_image(raw_image, new_w: int, new_h: int) -> int:
    """Re-encode an image stream as JPEG q=85. Returns new byte length."""
    pi = pikepdf.PdfImage(raw_image)
    pil = pi.as_pil_image()
    if pil.mode not in ("RGB", "L"):
        pil = pil.convert("RGB")
    pil = pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=85, optimize=True)
    jpeg = buf.getvalue()
    raw_image.write(
        jpeg, filter=pikepdf.Name("/DCTDecode"), decode_parms=pikepdf.Dictionary(),
    )
    raw_image.Width = new_w
    raw_image.Height = new_h
    raw_image.BitsPerComponent = 8
    raw_image.ColorSpace = (
        pikepdf.Name("/DeviceGray") if pil.mode == "L" else pikepdf.Name("/DeviceRGB")
    )
    return len(jpeg)


def _downsample_one_smask(smask, new_w: int, new_h: int) -> int:
    """Re-encode SMask as raw 8-bit gray + Flate. Returns new compressed length."""
    pi = pikepdf.PdfImage(smask)
    pil = pi.as_pil_image()
    if pil.mode != "L":
        pil = pil.convert("L")
    pil = pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
    raw = pil.tobytes()
    comp = zlib.compress(raw, level=9)
    smask.write(
        comp, filter=pikepdf.Name("/FlateDecode"), decode_parms=pikepdf.Dictionary(),
    )
    smask.Width = new_w
    smask.Height = new_h
    smask.BitsPerComponent = 8
    smask.ColorSpace = pikepdf.Name("/DeviceGray")
    return len(comp)


def _downsample_pdf_images(pdf_path: Path, target_dpi: int) -> None:
    """
    Walk every embedded image; downsample those whose effective DPI on the page
    exceeds target_dpi. SMasks are processed in lockstep (preserves alpha).
    Deduplicates by xref. Per-image errors are isolated to stderr; batch continues.

    Algorithm validated in /tmp/test_compress.py phase2 against PowerPoint
    exports with SMask-heavy decks. Matches ghostscript /screen, /ebook, /printer
    file-size results within a few percent.
    """
    pdf = pikepdf.open(pdf_path, allow_overwriting_input=True)
    processed: set[int] = set()
    n_resized = 0

    try:
        for page in pdf.pages:
            try:
                ctms = _parse_content_stream_ctms(page)
                # Walk page resources to find image XObjects by name.
                # Replacement for the deprecated Page.images mapping;
                # preserves the {name: raw_image} access pattern we need
                # to correlate with CTM-derived display rects.
                resources = page.get("/Resources", pikepdf.Dictionary())
                xobjects = resources.get("/XObject", pikepdf.Dictionary())
                images = {
                    name: obj for name, obj in xobjects.items()
                    if obj.get("/Subtype") == pikepdf.Name("/Image")
                }
            except Exception:
                continue

            for name, raw_image in images.items():
                xref = raw_image.objgen[0]
                if xref in processed:
                    continue
                processed.add(xref)

                try:
                    pi = pikepdf.PdfImage(raw_image)
                    ow, oh = pi.width, pi.height
                except Exception:
                    continue

                rect = ctms.get(name)
                if rect is None:
                    continue
                dwi, dhi = rect[0] / 72.0, rect[1] / 72.0
                if dwi <= 0 or dhi <= 0:
                    continue
                eff = max(ow / dwi, oh / dhi)
                if eff <= target_dpi:
                    continue

                scale = target_dpi / eff
                nw = max(1, round(ow * scale))
                nh = max(1, round(oh * scale))

                try:
                    _downsample_one_image(raw_image, nw, nh)
                    sm = raw_image.get("/SMask")
                    if sm is not None:
                        smpi = pikepdf.PdfImage(sm)
                        sw = max(1, round(smpi.width * (nw / ow)))
                        sh = max(1, round(smpi.height * (nh / oh)))
                        _downsample_one_smask(sm, sw, sh)
                    n_resized += 1
                except Exception as e:
                    print(f"  ⚠️  image xref={xref}: {e}", file=sys.stderr)

        pdf.save(pdf_path)
        if n_resized:
            print(f"  ↓ downsampled {n_resized} images (target {target_dpi} DPI)", file=sys.stderr)
    finally:
        pdf.close()


def stage_pptx_to_pdf(input_path: Path, opts: dict, workdir: Path) -> Path:
    """
    Convert PPTX to PDF using Microsoft PowerPoint via AppleScript (macOS only).

    Options:
      compress: none / small / medium / large
        none   — PowerPoint's raw export, no post-processing
        small  — image downsampling to 72 DPI (screen viewing)
        medium — 150 DPI (balanced, default)
        large  — 300 DPI (print quality)
    """
    global _PPTX_LAUNCHED_BY_US

    if platform.system() != "Darwin":
        raise RuntimeError(
            "pptx_to_pdf currently requires macOS + Microsoft PowerPoint. "
            "Cross-platform support (LibreOffice headless / Windows COM) is on the roadmap."
        )

    compress = opts.get("compress", "medium")
    if compress not in _DPI_PRESETS:
        raise ValueError(f"Unknown --pptx-compress value: {compress!r}")

    output_path = workdir  # runner passes the resolved output path

    # Track if PowerPoint was already running BEFORE we touched it.
    # First call in a batch sets the flag for the rest.
    if not _PPTX_LAUNCHED_BY_US and not _powerpoint_is_running():
        _PPTX_LAUNCHED_BY_US = True

    # AppleScript: open, hide, save as PDF, close.
    applescript = f'''
    tell application "Microsoft PowerPoint"
        set theFile to POSIX file "{input_path}"
        set theOutput to POSIX file "{output_path}"
        open theFile
        tell application "System Events"
            set visible of process "Microsoft PowerPoint" to false
        end tell
        set theDoc to active presentation
        save theDoc in theOutput as save as PDF
        close theDoc saving no
    end tell
    '''

    result = subprocess.run(
        ["osascript", "-e", applescript],
        capture_output=True, text=True, timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"PowerPoint export failed for {input_path.name}:\n{result.stderr.strip()}"
        )

    if not output_path.exists():
        raise RuntimeError(
            f"PowerPoint export reported success but file was not created: {output_path}"
        )

    # Post-process: image downsampling + cleanup
    dpi = _DPI_PRESETS[compress]
    if dpi is not None:
        try:
            _downsample_pdf_images(output_path, dpi)
        except Exception as e:
            print(f"⚠️  Image downsampling failed ({e}); keeping uncompressed PDF", file=sys.stderr)

    return output_path


# ─── Stage registry ───────────────────────────────────────────────────────────

STAGES: dict[str, Stage] = {
    "pdf_to_txt": Stage(
        src="pdf", dst="txt", fn=stage_pdf_to_txt,
        options=[
            StageOption(
                name="layout",
                choices=["layout", "plain"],
                default="layout",
                help="Preserve columns/tables via row reconstruction (layout), or extract reading-order text (plain).",
            ),
        ],
    ),
    "images_to_pdf": Stage(
        src="images", dst="pdf", fn=stage_images_to_pdf,
        multi_input=True,
        options=[
            StageOption(
                name="page-size",
                choices=["auto", "letter", "a4"],
                default="auto",
                help="auto = page sized to each image. letter/a4 = fixed page, image contain-fit and centered with auto-orientation.",
            ),
        ],
    ),
    "pptx_to_pdf": Stage(
        src="pptx", dst="pdf", fn=stage_pptx_to_pdf,
        options=[
            StageOption(
                name="compress",
                choices=["none", "small", "medium", "large"],
                default="medium",
                help="Image quality: none (raw), small (72 DPI), medium (150 DPI, default), large (300 DPI).",
            ),
        ],
    ),
}

# Edges = directed adjacency map for BFS routing
EDGES: dict[str, list[str]] = {}
for stage in STAGES.values():
    EDGES.setdefault(stage.src, []).append(stage.dst)


# ─── Routing ──────────────────────────────────────────────────────────────────

def find_chain(src: str, dst: str) -> list[Stage]:
    """BFS over EDGES to find a stage chain from src to dst."""
    if src == dst:
        raise ValueError(f"--from and --to are both {src!r}; nothing to do.")

    # BFS recording the predecessor for each visited node
    prev: dict[str, str | None] = {src: None}
    queue: deque[str] = deque([src])
    while queue:
        cur = queue.popleft()
        if cur == dst:
            break
        for nxt in EDGES.get(cur, []):
            if nxt not in prev:
                prev[nxt] = cur
                queue.append(nxt)

    if dst not in prev:
        available = sorted({s for s in EDGES} | {d for ds in EDGES.values() for d in ds})
        raise ValueError(
            f"No conversion path from {src!r} to {dst!r}.\n"
            f"Available formats: {available}\n"
            f"Available edges:   {dict(EDGES)}"
        )

    # Reconstruct path
    chain_formats: list[str] = []
    cur: str | None = dst
    while cur is not None:
        chain_formats.append(cur)
        cur = prev[cur]
    chain_formats.reverse()

    return [STAGES[f"{a}_to_{b}"] for a, b in zip(chain_formats, chain_formats[1:])]


# ─── Output naming + intermediate handling ────────────────────────────────────

def resolve_output_path(
    desired_dir: Path, stem: str, ext: str, force: bool
) -> Path:
    """
    Return a path under desired_dir named `{stem}.{ext}`. If it exists and
    --force is not set, append _1, _2, ... until free.
    """
    candidate = desired_dir / f"{stem}.{ext}"
    if force or not candidate.exists():
        return candidate

    n = 1
    while True:
        candidate = desired_dir / f"{stem}_{n}.{ext}"
        if not candidate.exists():
            return candidate
        n += 1


# ─── Input expansion + validation ─────────────────────────────────────────────

def expand_inputs(raw: list[str], src_format: str) -> list[Path]:
    """
    Expand a mixed list of files and directories into a flat list of file paths.

    Directories are expanded to their sorted contents, filtered to the source
    format's recognized extensions. Individual files are validated against the
    same extension set — wrong extensions fail fast with a clear error before
    any stage runs (defense at the boundary; stages may still do deeper
    content-level validation).

    Preserves the user's argv order: each directory expands in-place at its
    position in the list, alphabetically within itself.
    """
    allowed_exts = FORMAT_EXTENSIONS.get(src_format, set())
    expanded: list[Path] = []
    for raw_path in raw:
        p = Path(raw_path).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"Input not found: {p}")
        if p.is_dir():
            if not allowed_exts:
                raise ValueError(
                    f"Cannot expand directory '{p}': format '{src_format}' "
                    f"has no recognized extensions"
                )
            matches = sorted(
                child for child in p.iterdir()
                if child.is_file() and child.suffix.lower() in allowed_exts
            )
            if not matches:
                raise ValueError(
                    f"No files matching {sorted(allowed_exts)} in directory: {p}"
                )
            expanded.extend(matches)
        else:
            # Individual file: enforce extension match if the format declares one.
            if allowed_exts and p.suffix.lower() not in allowed_exts:
                raise ValueError(
                    f"Input '{p.name}' does not match expected extensions "
                    f"for format '{src_format}': {sorted(allowed_exts)}"
                )
            expanded.append(p)
    return expanded


# ─── Run a chain on a single input ────────────────────────────────────────────

def _run_single_chain(
    input_path: Path,
    chain: list[Stage],
    stage_opts: dict[str, dict],
    out_path: Path | None,
    keep_intermediate: bool,
    force: bool,
) -> Path:
    """Run a chain (all single-input stages) on one input. Returns final path."""
    print(f"📄 {input_path.name}", file=sys.stderr)

    if keep_intermediate or out_path:
        # Persistent intermediates next to input; final lands at --out or default
        current = input_path
        for i, stage in enumerate(chain):
            is_last = (i == len(chain) - 1)
            if is_last and out_path is not None:
                target_dir = out_path.parent
                target_stem = out_path.stem
                target = resolve_output_path(target_dir, target_stem, stage.dst, force)
            else:
                target_dir = input_path.parent
                target = resolve_output_path(target_dir, current.stem, stage.dst, force)

            print(f"   → {stage.name}", file=sys.stderr)
            t0 = time.time()
            produced = stage.fn(current, stage_opts[stage.name], target)
            elapsed = time.time() - t0
            print(f"   ✅ {produced.name}  ({elapsed:.1f}s)", file=sys.stderr)
            current = produced
        return current
    else:
        # Throwaway intermediates in tempdir, only final keeps
        with tempfile.TemporaryDirectory(prefix="docpipe_") as td:
            tdpath = Path(td)
            current = input_path
            for i, stage in enumerate(chain):
                is_last = (i == len(chain) - 1)
                if is_last:
                    target_dir = (out_path.parent if out_path else input_path.parent)
                    target_stem = (out_path.stem if out_path else current.stem)
                    target = resolve_output_path(target_dir, target_stem, stage.dst, force)
                else:
                    target = tdpath / f"{current.stem}.{stage.dst}"

                print(f"   → {stage.name}", file=sys.stderr)
                t0 = time.time()
                produced = stage.fn(current, stage_opts[stage.name], target)
                elapsed = time.time() - t0
                print(f"   ✅ {produced.name}  ({elapsed:.1f}s)", file=sys.stderr)
                current = produced
            return current


def _run_multi_chain(
    inputs: list[Path],
    chain: list[Stage],
    stage_opts: dict[str, dict],
    out_path: Path,
    keep_intermediate: bool,
    force: bool,
) -> Path:
    """
    Run a chain whose FIRST stage is multi_input. The first stage consumes
    the full input list and produces a single intermediate. Subsequent stages
    (if any) run single-input over that intermediate.
    """
    print(f"📦 {len(inputs)} inputs → {chain[0].dst}", file=sys.stderr)

    target = resolve_output_path(out_path.parent, out_path.stem, chain[0].dst, force)

    print(f"   → {chain[0].name}", file=sys.stderr)
    t0 = time.time()
    first_out = chain[0].fn(inputs, stage_opts[chain[0].name], target)
    elapsed = time.time() - t0
    print(f"   ✅ {first_out.name}  ({elapsed:.1f}s)", file=sys.stderr)

    if len(chain) == 1:
        return first_out

    # Continue with remaining single-input stages
    return _run_single_chain(
        first_out, chain[1:], stage_opts, out_path, keep_intermediate, force,
    )


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    formats = sorted(set(FORMAT_EXTENSIONS.keys()) | {s.src for s in STAGES.values()} | {s.dst for s in STAGES.values()})

    p = argparse.ArgumentParser(
        prog="docpipe",
        description="Unified document conversion pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--from", dest="src", choices=formats,
                   help="Source format")
    p.add_argument("--to", dest="dst", choices=formats,
                   help="Destination format")
    p.add_argument("--out", type=Path, default=None,
                   help="Explicit output path (overrides default naming). "
                        "Required for multi-input stages (e.g. images→pdf). "
                        "Rejected when batching multiple single-input files.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing outputs instead of appending _1, _2, ...")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the resolved chain and intended actions, then exit.")
    p.add_argument("--introspect", action="store_true",
                   help="Print the conversion graph + per-stage options as JSON, then exit.")
    p.add_argument("--keep-intermediate", dest="keep_intermediate",
                   action="store_true", default=True,
                   help="Keep intermediate files from each stage (default).")
    p.add_argument("--no-keep-intermediate", dest="keep_intermediate",
                   action="store_false",
                   help="Discard intermediate files, only keep final output.")

    # Per-stage options, namespaced as --{src}-{name}
    for stage in STAGES.values():
        for opt in stage.options:
            p.add_argument(
                f"--{stage.src}-{opt.name}",
                dest=f"opt_{stage.name}_{opt.name.replace('-', '_')}",
                choices=opt.choices,
                default=opt.default,
                help=opt.help,
            )

    p.add_argument("--out-dir", type=Path, default=None,
                   help="Directory to write outputs to. Auto-names within the directory. "
                        "Mutually exclusive with --out.")
    p.add_argument("--echo", action="store_true",
                   help="Debug: print argv as JSON to stdout and exit. "
                        "Used by the renderer to verify flag wiring.")
    p.add_argument("inputs", nargs="*", type=str,
                   help="Input file paths or directories.")
    return p


def introspect_payload() -> dict:
    return {
        "formats": sorted(set(s.src for s in STAGES.values()) | set(s.dst for s in STAGES.values())),
        "edges": [
            {
                "from": stage.src,
                "to": stage.dst,
                "multi_input": stage.multi_input,
                "extensions": sorted(FORMAT_EXTENSIONS.get(stage.src, set())),
                "options": [
                    {
                        "name": opt.name,
                        "flag": f"--{stage.src}-{opt.name}",
                        "choices": opt.choices,
                        "default": opt.default,
                        "help": opt.help,
                    }
                    for opt in stage.options
                ],
            }
            for stage in STAGES.values()
        ],
        "version": 3,
    }


def main(argv: list[str] | None = None) -> int:
    # Intercept --echo BEFORE argparse so it survives even invalid args.
    # The whole point of --echo is to inspect what reached the script,
    # which matters most when something is wrong.
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if "--echo" in raw_argv:
        payload = {"received_argv": raw_argv}
        print(json.dumps(payload, indent=2))
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.introspect:
        print(json.dumps(introspect_payload(), indent=2))
        return 0

    if not args.src or not args.dst:
        parser.error("--from and --to are required (unless --introspect)")

    if not args.inputs:
        parser.error("at least one input is required")

    # Resolve chain
    try:
        chain = find_chain(args.src, args.dst)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    # Per-stage option dict
    stage_opts: dict[str, dict] = {}
    for stage in chain:
        opts: dict = {}
        for opt in stage.options:
            attr = f"opt_{stage.name}_{opt.name.replace('-', '_')}"
            opts[opt.name.replace("-", "_")] = getattr(args, attr)
        stage_opts[stage.name] = opts

    # Expand + validate inputs
    try:
        inputs = expand_inputs(args.inputs, args.src)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    first_stage = chain[0]

    # --out vs --out-dir mutual exclusion
    if args.out is not None and args.out_dir is not None:
        print("❌ --out and --out-dir are mutually exclusive", file=sys.stderr)
        return 1

    # --out semantics enforcement
    if first_stage.multi_input:
        if args.out is None:
            print(
                f"❌ --out is required for multi-input stages "
                f"({first_stage.src} → {first_stage.dst} combines N inputs into 1 output)",
                file=sys.stderr,
            )
            return 1
    else:
        if args.out is not None and len(inputs) > 1:
            print(
                f"❌ --out cannot be used with multiple inputs in a "
                f"{first_stage.src} → {first_stage.dst} chain "
                f"(each input produces its own output). "
                f"Remove --out, or pass a single input.",
                file=sys.stderr,
            )
            return 1

    # Dry-run
    if args.dry_run:
        print("Chain: " + " → ".join([chain[0].src] + [s.dst for s in chain]))
        for stage in chain:
            print(f"  {stage.name}  {stage_opts[stage.name]}")
        if first_stage.multi_input:
            print(f"Inputs ({len(inputs)}):")
            for inp in inputs:
                print(f"  {inp}")
            print(f"Output: {args.out}")
        else:
            for inp in inputs:
                print(f"Input:  {inp}")
            if args.out:
                print(f"Output: {args.out}")
        return 0

    # Execute
    final_outputs: list[Path] = []
    failures: list[tuple[Path, Exception]] = []

    if first_stage.multi_input:
        # N → 1: one shot
        try:
            final = _run_multi_chain(
                inputs, chain, stage_opts, args.out,
                args.keep_intermediate, args.force,
            )
            final_outputs.append(final)
        except Exception as e:
            print(f"❌ {e}", file=sys.stderr)
            return 2
    else:
        # N → N: loop with per-file error isolation
        for inp in inputs:
            # Derive the effective output path: explicit --out wins; else if
            # --out-dir is set, auto-name within it; else default (alongside input).
            effective_out = args.out if len(inputs) == 1 else None
            if effective_out is None and args.out_dir is not None:
                last = chain[-1]
                effective_out = args.out_dir / f"{inp.stem}.{last.dst}"
            try:
                final = _run_single_chain(
                    inp, chain, stage_opts,
                    effective_out,
                    args.keep_intermediate, args.force,
                )
                final_outputs.append(final)
            except Exception as e:
                print(f"❌ {inp.name}: {e}", file=sys.stderr)
                failures.append((inp, e))

    # Final outputs to stdout (one per line) — lets callers parse what was produced
    for f in final_outputs:
        print(f)

    if len(inputs) > 1 and not first_stage.multi_input:
        print(f"── {len(final_outputs)} ok, {len(failures)} failed", file=sys.stderr)

    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
