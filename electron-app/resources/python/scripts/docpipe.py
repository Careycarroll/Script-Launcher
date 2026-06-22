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
  docpipe --no-keep-intermediate ...     # delete intermediates (default: keep)
  docpipe --force                        # overwrite existing outputs
  docpipe --dry-run                      # print resolved chain, do not execute
  docpipe --introspect                   # print graph + options as JSON
"""

from __future__ import annotations

import argparse
import json
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
    Combine images into a single PDF, one page per image, in the order given.

    Multi-input stage (N images → 1 PDF). Output name comes from --out; the
    CLI enforces that --out is provided for multi_input stages.

    Options:
      page_size: 'auto' (default) — each page sized to its own image.
                 'letter' / 'a4' — fixed page size; image fitted via 'contain'
                 (whole image visible, letterbox margins, no distortion).
    """
    page_size = opts.get("page_size", "auto")
    # workdir IS the output path for multi_input stages — set by run_chain
    output_path = workdir

    out_doc = pymupdf.open()
    try:
        for img_path in inputs:
            # Open as image; convert to single-page PDF bytes via PyMuPDF's
            # native image→PDF conversion (preserves resolution, no re-encode).
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
                    # Page exactly matches image dimensions
                    new_page = out_doc.new_page(width=img_w, height=img_h)
                    new_page.show_pdf_page(new_page.rect, img_pdf, 0)
                else:
                    # Fixed page size with 'contain' fit
                    pw, ph = _PAGE_SIZES_PT[page_size]
                    # Auto-rotate: if image is landscape and page is portrait
                    # (or vice versa), swap the page dimensions to match
                    img_landscape  = img_w > img_h
                    page_landscape = pw > ph
                    if img_landscape != page_landscape:
                        pw, ph = ph, pw

                    new_page = out_doc.new_page(width=pw, height=ph)

                    # Contain: scale to fit within page, preserve aspect ratio
                    scale = min(pw / img_w, ph / img_h)
                    draw_w = img_w * scale
                    draw_h = img_h * scale
                    x0 = (pw - draw_w) / 2
                    y0 = (ph - draw_h) / 2
                    target_rect = pymupdf.Rect(x0, y0, x0 + draw_w, y0 + draw_h)
                    new_page.show_pdf_page(target_rect, img_pdf, 0)
            finally:
                img_pdf.close()

        out_doc.save(output_path)
    finally:
        out_doc.close()

    return output_path


# ─── Stage registry ───────────────────────────────────────────────────────────

STAGES: dict[str, Stage] = {
    "pdf_to_txt": Stage(
        src="pdf",
        dst="txt",
        fn=stage_pdf_to_txt,
        multi_input=False,
        options=[
            StageOption(
                name="layout",
                choices=["layout", "plain"],
                default="layout",
                help="Reconstruct columns/tables via y-binning + x-padding (layout, default), or extract as plain reading-order text (plain).",
            ),
        ],
    ),
    "images_to_pdf": Stage(
        src="images",
        dst="pdf",
        fn=stage_images_to_pdf,
        multi_input=True,
        options=[
            StageOption(
                name="page-size",
                choices=["auto", "letter", "a4"],
                default="auto",
                help="auto (default) sizes each page to its image. letter/a4 use fixed page size with the image scaled to fit (contain, no distortion).",
            ),
        ],
    ),
    # Stubs — wired in subsequent slices:
    # "docx_to_pdf":   Stage(...),
    # "pptx_to_pdf":   Stage(...),
    # "pdf_to_md":     Stage(...),
    # "txt_to_md":     Stage(...),
}

# Edges define the conversion graph. Derived from STAGES.
EDGES: dict[str, list[str]] = {}
for stage in STAGES.values():
    EDGES.setdefault(stage.src, []).append(stage.dst)


# ─── Routing ──────────────────────────────────────────────────────────────────

def route(src: str, dst: str) -> list[Stage]:
    """BFS over EDGES to find the shortest stage chain from src to dst."""
    if src == dst:
        raise ValueError(f"Source and destination are identical: {src}")

    queue: deque[tuple[str, list[str]]] = deque([(src, [src])])
    visited: set[str] = {src}

    while queue:
        current, path = queue.popleft()
        for nxt in EDGES.get(current, []):
            if nxt in visited:
                continue
            new_path = path + [nxt]
            if nxt == dst:
                return [STAGES[f"{new_path[i]}_to_{new_path[i+1]}"]
                        for i in range(len(new_path) - 1)]
            visited.add(nxt)
            queue.append((nxt, new_path))

    raise ValueError(f"No conversion path: {src} → {dst}")


# ─── Input expansion ──────────────────────────────────────────────────────────

def expand_inputs(raw_inputs: list[str], src_format: str) -> list[Path]:
    """
    Resolve argv input strings to a flat list of file paths.

    - File paths pass through verified to exist
    - Directory paths expand to their sorted contents, filtered by the source
      format's recognized extensions

    Raises FileNotFoundError or ValueError on bad input.
    """
    extensions = FORMAT_EXTENSIONS.get(src_format, set())
    result: list[Path] = []

    for raw in raw_inputs:
        p = Path(raw).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Input not found: {raw}")

        if p.is_dir():
            if not extensions:
                raise ValueError(
                    f"Directory input requires known extensions for format "
                    f"'{src_format}', but none registered."
                )
            matches = sorted(
                child for child in p.iterdir()
                if child.is_file() and child.suffix.lower() in extensions
            )
            if not matches:
                raise ValueError(
                    f"No {src_format} files found in directory: {p}"
                )
            result.extend(matches)
        else:
            # Accept any file the user explicitly named, even if extension
            # doesn't match — they know what they're doing.
            result.append(p)

    return result


# ─── Output naming ────────────────────────────────────────────────────────────

def _resolve_output_path(stem: str, ext: str, parent: Path, force: bool) -> Path:
    """
    Build an output path at parent/stem.ext. If it exists and force is False,
    append _1, _2, ... until free.
    """
    candidate = parent / f"{stem}.{ext}"
    if force or not candidate.exists():
        return candidate
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}.{ext}"
        if not candidate.exists():
            return candidate
        i += 1


# ─── Execution ────────────────────────────────────────────────────────────────

def _opts_for_stage(stage: Stage, parsed_args: argparse.Namespace) -> dict:
    """Pull this stage's options out of parsed argparse namespace."""
    opts: dict[str, str] = {}
    for opt in stage.options:
        # CLI flag --pdf-layout → argparse attribute pdf_layout
        attr = f"{stage.src}_{opt.name}".replace("-", "_")
        opts[opt.name.replace("-", "_")] = getattr(parsed_args, attr, opt.default)
    return opts


def _run_single_chain(
    input_path: Path,
    chain: list[Stage],
    parsed_args: argparse.Namespace,
    final_out: Path | None,
    keep_intermediate: bool,
    force: bool,
) -> Path:
    """
    Run a chain where every stage is single-input (N→N batching path).
    Each stage produces 1 output that becomes the next stage's input.
    """
    print(f"📄 {input_path.name}", file=sys.stderr)
    t_start = time.monotonic()

    current = input_path
    if keep_intermediate:
        # Write intermediates and final output to input's directory
        parent = input_path.parent
    else:
        parent = Path(tempfile.mkdtemp(prefix="docpipe_"))

    for i, stage in enumerate(chain):
        print(f"   → {stage.name}", file=sys.stderr)
        is_last = i == len(chain) - 1

        if is_last and final_out is not None:
            target = final_out
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target_parent = input_path.parent if (is_last and keep_intermediate) else parent
            target = _resolve_output_path(current.stem, stage.dst, target_parent, force)

        opts = _opts_for_stage(stage, parsed_args)
        produced = stage.fn(current, opts, target)
        # Stage may return a different path than `target` if it added a suffix;
        # honor whatever it actually wrote.
        current = produced

    elapsed = time.monotonic() - t_start
    print(f"   ✅ {current.name}  ({elapsed:.1f}s)", file=sys.stderr)
    return current


def _run_multi_chain(
    inputs: list[Path],
    chain: list[Stage],
    parsed_args: argparse.Namespace,
    final_out: Path,
    keep_intermediate: bool,
    force: bool,
) -> Path:
    """
    Run a chain whose FIRST stage is multi_input (N→1 collapse).
    The collapse happens at stage 0; subsequent stages are single-input.
    """
    first = chain[0]
    rest = chain[1:]

    print(f"📦 {len(inputs)} inputs → {first.dst}", file=sys.stderr)
    t_start = time.monotonic()

    if keep_intermediate:
        parent = final_out.parent
    else:
        parent = Path(tempfile.mkdtemp(prefix="docpipe_"))

    # First stage produces the collapsed output.
    # If there are no further stages, write directly to final_out;
    # otherwise write to an intermediate path.
    if not rest:
        first_target = final_out
        first_target.parent.mkdir(parents=True, exist_ok=True)
    else:
        first_target = _resolve_output_path(
            final_out.stem, first.dst, parent, force
        )

    print(f"   → {first.name}", file=sys.stderr)
    opts = _opts_for_stage(first, parsed_args)
    current = first.fn(inputs, opts, first_target)

    # Remaining single-input stages
    for i, stage in enumerate(rest):
        print(f"   → {stage.name}", file=sys.stderr)
        is_last = i == len(rest) - 1
        if is_last:
            target = final_out
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target = _resolve_output_path(current.stem, stage.dst, parent, force)
        opts = _opts_for_stage(stage, parsed_args)
        current = stage.fn(current, opts, target)

    elapsed = time.monotonic() - t_start
    print(f"   ✅ {current.name}  ({elapsed:.1f}s)", file=sys.stderr)
    return current


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docpipe",
        description="Unified document conversion pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    all_formats = sorted(set(EDGES.keys()) | {d for ds in EDGES.values() for d in ds})

    parser.add_argument("--from", dest="from_fmt", choices=all_formats,
                        help="Source format")
    parser.add_argument("--to",   dest="to_fmt",   choices=all_formats,
                        help="Destination format")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output path (required for multi-input stages "
                             "like images→pdf; rejected when batching N→N).")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing output files.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print resolved chain and exit without converting.")
    parser.add_argument("--introspect", action="store_true",
                        help="Print graph + options as JSON and exit.")

    # Intermediate handling — default keep (per project decision)
    intermediate = parser.add_mutually_exclusive_group()
    intermediate.add_argument("--keep-intermediate", dest="keep_intermediate",
                              action="store_true", default=True,
                              help="Keep intermediate files alongside input "
                                   "(default).")
    intermediate.add_argument("--no-keep-intermediate", dest="keep_intermediate",
                              action="store_false",
                              help="Delete intermediate files (use temp dir).")

    # Auto-register every stage's options as namespaced flags
    for stage in STAGES.values():
        for opt in stage.options:
            flag = f"{stage.flag_prefix}-{opt.name}"
            parser.add_argument(
                flag,
                choices=opt.choices,
                default=opt.default,
                help=opt.help,
            )

    parser.add_argument("inputs", nargs="*", help="Input file(s) or directory.")
    return parser


def cmd_introspect() -> int:
    payload = {
        "formats": sorted(set(EDGES.keys()) | {d for ds in EDGES.values() for d in ds}),
        "edges": [
            {
                "from": s.src,
                "to": s.dst,
                "multi_input": s.multi_input,
                "options": [
                    {
                        "name": o.name,
                        "flag": f"{s.flag_prefix}-{o.name}",
                        "choices": o.choices,
                        "default": o.default,
                        "help": o.help,
                    }
                    for o in s.options
                ],
            }
            for s in STAGES.values()
        ],
        "version": 2,
    }
    print(json.dumps(payload, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.introspect:
        return cmd_introspect()

    if not args.from_fmt or not args.to_fmt:
        print("docpipe: --from and --to are required (or use --introspect)",
              file=sys.stderr)
        return 1

    try:
        chain = route(args.from_fmt, args.to_fmt)
    except ValueError as e:
        print(f"docpipe: {e}", file=sys.stderr)
        return 1

    if not args.inputs:
        print("docpipe: at least one input is required", file=sys.stderr)
        return 1

    try:
        inputs = expand_inputs(args.inputs, args.from_fmt)
    except (FileNotFoundError, ValueError) as e:
        print(f"docpipe: {e}", file=sys.stderr)
        return 1

    first_stage = chain[0]
    is_multi = first_stage.multi_input

    # --out semantics:
    #   multi_input stage  → REQUIRED (N inputs collapse to 1 output)
    #   single-input + 1 input  → optional, overrides default naming
    #   single-input + N inputs (batching N→N) → REJECTED (ambiguous)
    if is_multi:
        if args.out is None:
            print(f"docpipe: --out is required for {first_stage.name} "
                  f"(N inputs → 1 output)", file=sys.stderr)
            return 1
    else:
        if len(inputs) > 1 and args.out is not None:
            print("docpipe: --out is incompatible with multiple inputs when "
                  "each input produces its own output. Drop --out, or pass a "
                  "single input.", file=sys.stderr)
            return 1

    # Resolve final_out for multi_input case
    final_out: Path | None = None
    if is_multi:
        out = args.out.expanduser()
        if not out.is_absolute():
            # Resolve relative to first input's parent
            out = inputs[0].parent / out
        # If user gave an existing directory, that's an error — we need a filename
        if out.exists() and out.is_dir():
            print(f"docpipe: --out must be a filename, not a directory: {out}",
                  file=sys.stderr)
            return 1
        if out.exists() and not args.force:
            out = _resolve_output_path(out.stem, out.suffix.lstrip("."),
                                       out.parent, force=False)
        final_out = out
    else:
        if args.out is not None:
            final_out = args.out.expanduser()
            if not final_out.is_absolute():
                final_out = inputs[0].parent / final_out

    # ── Dry run ──
    if args.dry_run:
        print(f"Chain: {' → '.join([s.src for s in chain] + [chain[-1].dst])}")
        for s in chain:
            print(f"  {s.name}  {_opts_for_stage(s, args)}")
        if is_multi:
            print(f"Inputs ({len(inputs)}):")
            for p in inputs:
                print(f"  {p}")
            print(f"Output: {final_out}")
        else:
            for p in inputs:
                print(f"Input:  {p}")
            if final_out:
                print(f"Output: {final_out}")
        return 0

    # ── Execute ──
    if is_multi:
        try:
            produced = _run_multi_chain(
                inputs, chain, args,
                final_out=final_out,
                keep_intermediate=args.keep_intermediate,
                force=args.force,
            )
            print(produced)
            return 0
        except Exception as e:
            print(f"   ✗ failed: {e}", file=sys.stderr)
            return 2

    # Single-input chain: batch N→N
    ok = 0
    failed = 0
    produced_paths: list[Path] = []
    for input_path in inputs:
        try:
            produced = _run_single_chain(
                input_path, chain, args,
                final_out=final_out if len(inputs) == 1 else None,
                keep_intermediate=args.keep_intermediate,
                force=args.force,
            )
            produced_paths.append(produced)
            ok += 1
        except Exception as e:
            print(f"   ✗ {input_path.name}: {e}", file=sys.stderr)
            failed += 1

    for p in produced_paths:
        print(p)

    if len(inputs) > 1:
        print(f"── {ok} ok, {failed} failed", file=sys.stderr)

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
