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
                      --out is REQUIRED for multi_input stages (the output name
                      cannot be inferred when N>1 inputs collapse to 1 output).

Directory inputs are expanded in-place to their sorted contents, filtered to
formats the first stage's source format declares as recognized extensions.
This lets a user drop a folder of images and have it Just Work.

CLI:
  docpipe --from pdf --to txt input.pdf
  docpipe --from pdf --to txt a.pdf b.pdf c.pdf       # batch: N→N
  docpipe --from pdf --to txt input.pdf --out output.txt
  docpipe --from pdf --to txt input.pdf --pdf-layout plain
  docpipe --from images --to pdf img1.png img2.png --out combined.pdf
  docpipe --from images --to pdf ~/scans/ --out scans.pdf
  docpipe --from pptx --to pdf deck.pptx              # macOS + PowerPoint
  docpipe --from pptx --to pdf deck.pptx --pptx-compress no
  docpipe --no-keep-intermediate ...     # delete intermediates (default: keep)
  docpipe --force                        # overwrite existing outputs
  docpipe --dry-run                      # print resolved chain, do not execute
  docpipe --introspect                   # print graph + options as JSON
"""

from __future__ import annotations

import argparse
import atexit
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

import pymupdf  # PyMuPDF >= 1.24


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
        # All options for this stage are namespaced --<src>-<name>
        # e.g. pdf → txt's "layout" option becomes --pdf-layout
        return f"--{self.src}"


# ─── Format → recognized extensions ───────────────────────────────────────────
# Used for directory expansion: if a user passes a folder, only files matching
# the source format's extensions are picked up. Keep these lowercase.

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
    by y-coordinate and padding with spaces to approximate x position.

    Mirrors pdftotext -layout behavior. Not pixel-perfect — heuristic.
    """
    blocks = page.get_text("blocks")
    # block tuple: (x0, y0, x1, y1, text, block_no, block_type)
    # block_type 0 = text, 1 = image
    lines: list[tuple[float, float, float, float, str]] = []

    for b in blocks:
        if len(b) < 7 or b[6] != 0:
            continue
        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
        text = text.rstrip("\n")
        if not text.strip():
            continue

        # A block can contain multiple visual lines. Split and distribute
        # y-coordinates evenly across the block's vertical extent so each
        # line bins into the right row.
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

    # Normalize x: subtract the page's leftmost x0 so output starts at column 0
    min_x = min(l[0] for l in lines)
    if min_x > 0:
        lines = [(x0 - min_x, y0, x1, y1, t) for (x0, y0, x1, y1, t) in lines]

    # Sort by vertical position, then horizontal
    lines.sort(key=lambda l: (l[1], l[0]))

    # Group lines into rows by y-proximity. A new row starts when the next
    # line's y0 is more than _ROW_TOL_PT below the current row's reference y.
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

    # Emit each row as a single line with x-position-based space padding
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


# ─── Stage implementations ────────────────────────────────────────────────────

def stage_pdf_to_txt(input_path: Path, opts: dict, workdir: Path) -> Path:
    """
    Extract text from a PDF.

    Options:
      layout: 'layout' (default) reconstructs columns/tables via y-binning +
              x-padding — closest equivalent to pdftotext -layout.
              'plain' returns reading-order text without spatial reconstruction.
    """
    mode = opts.get("layout", "layout")
    output_path = workdir / f"{input_path.stem}.txt"

    doc = pymupdf.open(input_path)
    try:
        chunks: list[str] = []
        for page in doc:
            if mode == "layout":
                text = _layout_page_text(page)
            else:
                text = page.get_text("text")
            chunks.append(text)
        # Single newline between pages; no form-feeds (matches pdftotext -nopgbrk)
        output_path.write_text("\n".join(chunks), encoding="utf-8")
    finally:
        doc.close()

    return output_path


# Fixed page sizes in points (1 pt = 1/72 inch). Width × height, portrait.
_PAGE_SIZES_PT: dict[str, tuple[float, float]] = {
    "letter": (612.0, 792.0),    # 8.5 × 11 in
    "a4":     (595.28, 841.89),  # 210 × 297 mm
}


def stage_images_to_pdf(inputs: list[Path], opts: dict, workdir: Path) -> Path:
    """
    Combine images into a single PDF.

    Options:
      page_size: 'auto' (default) — each page sized to its image
                 'letter' / 'a4'  — fixed page size, contain-fit, auto-orient

    Multi-input: takes N images, produces 1 PDF. Output path comes from --out
    (CLI enforces this), routed through workdir as <workdir>/<--out basename>.
    """
    page_size = opts.get("page_size", "auto")

    # workdir already carries the desired output filename via run_chain when
    # --out is set on a multi_input stage. Use workdir as the output path.
    output_path = workdir

    out_doc = pymupdf.open()  # empty PDF
    try:
        for img_path in inputs:
            # Convert image → single-page PDF in memory, then merge
            img_doc = pymupdf.open(img_path)
            try:
                pdf_bytes = img_doc.convert_to_pdf()
            finally:
                img_doc.close()

            src = pymupdf.open("pdf", pdf_bytes)
            try:
                if page_size == "auto":
                    out_doc.insert_pdf(src)
                else:
                    # Determine target page dimensions, auto-orienting to match
                    # the image's aspect ratio (landscape image → landscape page)
                    img_rect = src[0].rect
                    pw, ph = _PAGE_SIZES_PT[page_size]
                    if img_rect.width > img_rect.height:
                        pw, ph = ph, pw  # landscape

                    page = out_doc.new_page(width=pw, height=ph)
                    # contain-fit: scale image to fit within page, centered
                    scale = min(pw / img_rect.width, ph / img_rect.height)
                    w = img_rect.width * scale
                    h = img_rect.height * scale
                    x = (pw - w) / 2
                    y = (ph - h) / 2
                    page.show_pdf_page(
                        pymupdf.Rect(x, y, x + w, y + h),
                        src,
                        0,
                    )
            finally:
                src.close()

        out_doc.save(output_path, garbage=4, deflate=True)
    finally:
        out_doc.close()

    return output_path


# ─── PowerPoint state (for pptx → pdf stage) ──────────────────────────────────
# We launch PowerPoint via AppleScript on the first PPTX in a batch and want
# to leave the user's environment as we found it: if PowerPoint wasn't running
# before, we quit it after the batch. These module-level flags coordinate that
# across multiple stage invocations within a single docpipe run.

_PPTX_PROBED        = False  # have we checked PowerPoint's running state?
_PPTX_WAS_RUNNING   = False  # was it already running when we started?
_PPTX_QUIT_REGISTERED = False  # have we registered the atexit quit hook?


def _pptx_check_running() -> bool:
    """Return True if Microsoft PowerPoint is currently running."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "Microsoft PowerPoint"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _pptx_quit_if_we_launched():
    """atexit hook — quit PowerPoint only if it wasn't running before we started."""
    if _PPTX_PROBED and not _PPTX_WAS_RUNNING:
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "Microsoft PowerPoint" to quit'],
                capture_output=True, timeout=10,
            )
            print("🔴 PowerPoint closed", file=sys.stderr)
        except (subprocess.SubprocessError, FileNotFoundError):
            pass  # best-effort cleanup


def stage_pptx_to_pdf(input_path: Path, opts: dict, workdir: Path) -> Path:
    """
    Convert a .pptx to PDF by automating Microsoft PowerPoint via AppleScript.

    macOS-only. Requires Microsoft PowerPoint to be installed.

    Options:
      compress: 'yes' (default) — pymupdf post-process with garbage collection,
                                  deflate, image+font deflate, clean
                'no'            — PowerPoint's raw PDF export, untouched

    Behavior:
      - Hides PowerPoint window during conversion (System Events)
      - Detects whether PowerPoint was already running on first call
      - Registers an atexit hook to quit PowerPoint if and only if WE launched it
    """
    global _PPTX_PROBED, _PPTX_WAS_RUNNING, _PPTX_QUIT_REGISTERED

    if platform.system() != "Darwin":
        raise RuntimeError(
            "pptx → pdf currently requires macOS + Microsoft PowerPoint. "
            "Cross-platform support is on the backlog."
        )

    # First-call: probe PowerPoint state and register the quit-after hook.
    # We do this lazily (here, not at import) so the introspect/dry-run paths
    # don't shell out to pgrep when no PPTX work will actually happen.
    if not _PPTX_PROBED:
        _PPTX_WAS_RUNNING = _pptx_check_running()
        _PPTX_PROBED = True
    if not _PPTX_QUIT_REGISTERED:
        atexit.register(_pptx_quit_if_we_launched)
        _PPTX_QUIT_REGISTERED = True

    compress = opts.get("compress", "yes") == "yes"
    output_path = workdir / f"{input_path.stem}.pdf"

    # If compressing, PowerPoint writes a temp PDF and we re-save through pymupdf.
    # If not, PowerPoint writes directly to the final output path.
    if compress:
        ppt_target = workdir / f"{input_path.stem}.ppt-raw.pdf"
    else:
        ppt_target = output_path

    # AppleScript: open file, hide PowerPoint, save as PDF, close doc.
    # POSIX paths are passed in directly via string interpolation — escape any
    # double quotes in the path defensively.
    in_str  = str(input_path.resolve()).replace('"', '\\"')
    out_str = str(ppt_target.resolve()).replace('"', '\\"')

    applescript = f'''
tell application "Microsoft PowerPoint"
    set theFile to POSIX file "{in_str}"
    set theOutput to POSIX file "{out_str}"
    open theFile
    tell application "System Events"
        if exists process "Microsoft PowerPoint" then
            set visible of process "Microsoft PowerPoint" to false
        end if
    end tell
    set theDoc to active presentation
    save theDoc in theOutput as save as PDF
    close theDoc saving no
end tell
'''.strip()

    result = subprocess.run(
        ["osascript", "-e", applescript],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"PowerPoint conversion failed for {input_path.name}: "
            f"{result.stderr.strip() or 'unknown osascript error'}"
        )

    if not ppt_target.exists():
        raise RuntimeError(
            f"PowerPoint reported success but no output file was produced: {ppt_target}"
        )

    # Compression pass: re-save through pymupdf with aggressive cleanup.
    # garbage=4 removes all unreferenced objects; deflate compresses streams;
    # deflate_images/fonts ensures image and font streams are also compressed;
    # clean=True runs the PDF parser cleanup pass.
    if compress:
        try:
            doc = pymupdf.open(ppt_target)
            try:
                doc.save(
                    output_path,
                    garbage=4,
                    deflate=True,
                    deflate_images=True,
                    deflate_fonts=True,
                    clean=True,
                )
            finally:
                doc.close()
        finally:
            # Always remove the intermediate PowerPoint-export PDF, even on
            # failure — it's a stage-internal artifact, not a pipeline-level
            # intermediate (which --keep-intermediate would govern).
            try:
                ppt_target.unlink()
            except FileNotFoundError:
                pass

    return output_path


# ─── Stage registry ───────────────────────────────────────────────────────────
# Single source of truth. The CLI, router, and introspection all read from here.

STAGES: dict[str, Stage] = {
    "pdf_to_txt": Stage(
        src="pdf", dst="txt", fn=stage_pdf_to_txt,
        options=[
            StageOption(
                name="layout",
                choices=["layout", "plain"],
                default="layout",
                help=(
                    "layout: reconstruct columns/tables via y-binning + x-padding "
                    "(default); plain: reading-order text only, no spatial layout."
                ),
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
                help=(
                    "auto: each page sized to its image (default); "
                    "letter/a4: fixed page size, image contain-fit and auto-oriented."
                ),
            ),
        ],
    ),
    "pptx_to_pdf": Stage(
        src="pptx", dst="pdf", fn=stage_pptx_to_pdf,
        options=[
            StageOption(
                name="compress",
                choices=["yes", "no"],
                default="yes",
                help=(
                    "yes: re-save via pymupdf with garbage collection + stream/image/"
                    "font deflate (default); no: keep PowerPoint's raw PDF export."
                ),
            ),
        ],
    ),
}

# Edges define the conversion graph. Source → destination → stage name.
EDGES: dict[str, dict[str, str]] = {
    "pdf":    {"txt": "pdf_to_txt"},
    "images": {"pdf": "images_to_pdf"},
    "pptx":   {"pdf": "pptx_to_pdf"},
}


# ─── Routing ──────────────────────────────────────────────────────────────────

def find_chain(src: str, dst: str) -> list[str]:
    """
    BFS over EDGES to find a path of stage names from src to dst.
    Returns [] if no path exists. Single-edge case returns [stage_name].
    """
    if src == dst:
        return []
    if src not in EDGES:
        return []

    # BFS with parent tracking
    visited = {src}
    queue: deque[tuple[str, list[str]]] = deque([(src, [])])
    while queue:
        node, path = queue.popleft()
        for next_fmt, stage_name in EDGES.get(node, {}).items():
            if next_fmt == dst:
                return path + [stage_name]
            if next_fmt not in visited:
                visited.add(next_fmt)
                queue.append((next_fmt, path + [stage_name]))
    return []


def all_formats() -> list[str]:
    """All known formats — sources of edges plus their destinations."""
    fmts = set(EDGES.keys())
    for dests in EDGES.values():
        fmts.update(dests.keys())
    return sorted(fmts)


# ─── Output naming ────────────────────────────────────────────────────────────

def resolve_output_path(
    desired: Path,
    force: bool,
) -> Path:
    """
    If `desired` doesn't exist, return it. Otherwise append _1, _2, ... until
    we find a free name. If force=True, return `desired` unchanged.
    """
    if force or not desired.exists():
        return desired
    stem = desired.stem
    suffix = desired.suffix
    parent = desired.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


# ─── Input expansion ──────────────────────────────────────────────────────────

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


# ─── Execution ────────────────────────────────────────────────────────────────

def _stage_opts(stage: Stage, args_ns: argparse.Namespace) -> dict:
    """Extract this stage's options from the argparse namespace."""
    out = {}
    for opt in stage.options:
        attr = f"{stage.src}_{opt.name}".replace("-", "_")
        out[opt.name.replace("-", "_")] = getattr(args_ns, attr, opt.default)
    return out


def _run_single_chain(
    input_path: Path,
    chain: list[str],
    args_ns: argparse.Namespace,
    out_override: Path | None,
    keep_intermediate: bool,
    force: bool,
) -> Path:
    """
    Run a chain of single-input stages on one input file. Returns final output.
    Intermediates live alongside the input (when keep_intermediate=True) or in
    a tempdir (when False).
    """
    current = input_path
    if keep_intermediate:
        intermediate_dir = input_path.parent
        tempdir_ctx = None
    else:
        tempdir_ctx = tempfile.TemporaryDirectory()
        intermediate_dir = Path(tempdir_ctx.name)

    try:
        last_idx = len(chain) - 1
        for i, stage_name in enumerate(chain):
            stage = STAGES[stage_name]
            opts = _stage_opts(stage, args_ns)

            # For the final stage, honor --out if provided; otherwise use the
            # input's directory with the stage's natural output name.
            if i == last_idx and out_override is not None:
                workdir = out_override.parent
            else:
                workdir = intermediate_dir

            start = time.time()
            print(f"   → {stage_name}", file=sys.stderr)
            produced = stage.fn(current, opts, workdir)

            # If this is the final stage and --out was specified, rename to it.
            if i == last_idx and out_override is not None and produced != out_override:
                target = resolve_output_path(out_override, force)
                produced.rename(target)
                produced = target
            elif i == last_idx:
                # Conflict resolution on natural names
                target = resolve_output_path(produced, force)
                if target != produced:
                    produced.rename(target)
                    produced = target

            elapsed = time.time() - start
            print(f"   ✅ {produced.name}  ({elapsed:.1f}s)", file=sys.stderr)
            current = produced

        return current
    finally:
        if tempdir_ctx is not None:
            tempdir_ctx.cleanup()


def _run_multi_chain(
    inputs: list[Path],
    chain: list[str],
    args_ns: argparse.Namespace,
    out_override: Path,
    keep_intermediate: bool,
    force: bool,
) -> Path:
    """
    Run a chain whose first stage is multi_input. The first stage receives the
    full list and produces a single output. Subsequent stages (if any) are
    single-input and run sequentially on that output.
    """
    if keep_intermediate:
        intermediate_dir = out_override.parent
        tempdir_ctx = None
    else:
        tempdir_ctx = tempfile.TemporaryDirectory()
        intermediate_dir = Path(tempdir_ctx.name)

    try:
        # First stage: multi_input
        first_name = chain[0]
        first_stage = STAGES[first_name]
        first_opts = _stage_opts(first_stage, args_ns)

        # If first stage IS the final stage, write directly to the resolved
        # output path. Otherwise write to intermediate dir with --out's basename.
        if len(chain) == 1:
            target = resolve_output_path(out_override, force)
        else:
            target = intermediate_dir / out_override.name

        print(f"   → {first_name}", file=sys.stderr)
        start = time.time()
        produced = first_stage.fn(inputs, first_opts, target)
        elapsed = time.time() - start
        print(f"   ✅ {produced.name}  ({elapsed:.1f}s)", file=sys.stderr)

        # Remaining stages: single-input on the produced file
        current = produced
        last_idx = len(chain) - 1
        for i, stage_name in enumerate(chain[1:], start=1):
            stage = STAGES[stage_name]
            opts = _stage_opts(stage, args_ns)
            workdir = out_override.parent if i == last_idx else intermediate_dir

            start = time.time()
            print(f"   → {stage_name}", file=sys.stderr)
            produced = stage.fn(current, opts, workdir)
            if i == last_idx:
                target = resolve_output_path(produced, force)
                if target != produced:
                    produced.rename(target)
                    produced = target
            elapsed = time.time() - start
            print(f"   ✅ {produced.name}  ({elapsed:.1f}s)", file=sys.stderr)
            current = produced

        return current
    finally:
        if tempdir_ctx is not None:
            tempdir_ctx.cleanup()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="docpipe",
        description="Unified document conversion pipeline.",
    )
    formats = all_formats()
    p.add_argument("--from", dest="src", choices=formats,
                   help="Source format")
    p.add_argument("--to", dest="dst", choices=formats,
                   help="Destination format")
    p.add_argument("--out", type=Path, default=None,
                   help="Override output path (single-input: optional; "
                        "multi-input: required; batched N→N: not allowed)")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing outputs (default: append _1, _2, ...)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print resolved chain and exit, no execution")
    p.add_argument("--introspect", action="store_true",
                   help="Print graph + options as JSON to stdout, exit")
    p.add_argument("--keep-intermediate", dest="keep_intermediate",
                   action="store_true", default=True,
                   help="Keep intermediate files alongside input (default)")
    p.add_argument("--no-keep-intermediate", dest="keep_intermediate",
                   action="store_false",
                   help="Delete intermediates after final output is produced")

    # Per-stage options auto-registered from STAGES
    for stage in STAGES.values():
        for opt in stage.options:
            flag = f"{stage.flag_prefix}-{opt.name}"
            p.add_argument(
                flag,
                choices=opt.choices,
                default=opt.default,
                help=opt.help or f"{stage.name} option",
            )

    p.add_argument("inputs", nargs="*",
                   help="Input file(s) or directories (directories expand to "
                        "their sorted contents, filtered to the source format)")
    return p


def emit_introspection() -> None:
    """Print the conversion graph + per-stage options as JSON to stdout."""
    edges_out = []
    for src, dests in EDGES.items():
        for dst, stage_name in dests.items():
            stage = STAGES[stage_name]
            edges_out.append({
                "from": src,
                "to": dst,
                "stage": stage_name,
                "multi_input": stage.multi_input,
                "options": [
                    {
                        "name": o.name,
                        "flag": f"{stage.flag_prefix}-{o.name}",
                        "choices": o.choices,
                        "default": o.default,
                        "help": o.help,
                    }
                    for o in stage.options
                ],
            })
    payload = {
        "formats": all_formats(),
        "edges": edges_out,
        "version": 2,
    }
    print(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.introspect:
        emit_introspection()
        return 0

    # Validate required args for non-introspect modes
    if not args.src or not args.dst:
        parser.error("--from and --to are required (unless --introspect)")
    if not args.inputs:
        parser.error("at least one input is required")

    chain = find_chain(args.src, args.dst)
    if not chain:
        parser.error(f"no conversion path from '{args.src}' to '{args.dst}'")

    # Expand directories to files (filtered to source format extensions)
    try:
        inputs = expand_inputs(args.inputs, args.src)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    first_stage = STAGES[chain[0]]
    is_multi = first_stage.multi_input
    is_batch = (not is_multi) and len(inputs) > 1

    # --out validation
    if is_multi and args.out is None:
        parser.error(
            f"--out is required for multi-input stages "
            f"({args.src} → {args.dst} takes N inputs → 1 output)"
        )
    if is_batch and args.out is not None:
        parser.error(
            f"--out cannot be used with multiple inputs in N→N batch mode "
            f"(each input produces its own output)"
        )

    # Resolve --out: if relative, place it next to the first input's parent
    out_override: Path | None = None
    if args.out is not None:
        out_path = args.out
        if not out_path.is_absolute():
            out_path = inputs[0].parent / out_path
        out_override = out_path

    # ── Dry run ─────────────────────────────────────────────────────────────
    if args.dry_run:
        print(f"Chain: {args.src} → {args.dst}", file=sys.stderr)
        for name in chain:
            stage = STAGES[name]
            opts = _stage_opts(stage, args)
            print(f"  {name}  {opts}", file=sys.stderr)
        if is_multi:
            print(f"Inputs ({len(inputs)}):", file=sys.stderr)
            for p in inputs:
                print(f"  {p}", file=sys.stderr)
            print(f"Output: {out_override}", file=sys.stderr)
        else:
            for p in inputs:
                print(f"Input:  {p}", file=sys.stderr)
        return 0

    # ── Execute ─────────────────────────────────────────────────────────────
    if is_multi:
        print(f"📦 {len(inputs)} inputs → {args.dst}", file=sys.stderr)
        try:
            final = _run_multi_chain(
                inputs, chain, args,
                out_override=out_override,  # required, guaranteed non-None above
                keep_intermediate=args.keep_intermediate,
                force=args.force,
            )
            print(final)
            return 0
        except Exception as e:
            print(f"❌ {e}", file=sys.stderr)
            return 2

    # Single-input chain — loop over inputs for batching
    ok, failed = 0, 0
    final_paths: list[Path] = []
    for input_path in inputs:
        print(f"📄 {input_path.name}", file=sys.stderr)
        try:
            final = _run_single_chain(
                input_path, chain, args,
                out_override=out_override if len(inputs) == 1 else None,
                keep_intermediate=args.keep_intermediate,
                force=args.force,
            )
            final_paths.append(final)
            ok += 1
        except Exception as e:
            print(f"   ❌ {e}", file=sys.stderr)
            failed += 1

    for p in final_paths:
        print(p)

    if len(inputs) > 1:
        print(f"── {ok} ok, {failed} failed", file=sys.stderr)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
