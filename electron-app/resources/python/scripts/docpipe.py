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

CLI:
  docpipe --from pdf --to txt input.pdf
  docpipe --from pdf --to txt a.pdf b.pdf c.pdf       # batch: N→N
  docpipe --from pdf --to txt input.pdf --out output.txt
  docpipe --from pdf --to txt input.pdf --pdf-layout plain
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
    # Stubs — wired in subsequent slices:
    # "images_to_pdf": Stage(..., multi_input=True),
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
    seen = {src}
    while queue:
        node, path = queue.popleft()
        for nxt in EDGES.get(node, []):
            if nxt == dst:
                full_path = path + [nxt]
                return [STAGES[f"{full_path[i]}_to_{full_path[i+1]}"]
                        for i in range(len(full_path) - 1)]
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, path + [nxt]))
    raise ValueError(f"No conversion path from {src} to {dst}")


# ─── Output path resolution ───────────────────────────────────────────────────

def _resolve_output_path(desired: Path, force: bool) -> Path:
    """
    If desired path exists and --force is not set, append _1, _2, ... until
    we find a free name. Returns the final path to use.
    """
    if force or not desired.exists():
        return desired
    stem, suffix, parent = desired.stem, desired.suffix, desired.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


# ─── Chain execution ──────────────────────────────────────────────────────────

def _run_single_chain(
    input_path: Path,
    chain: list[Stage],
    stage_opts: dict[str, dict],
    final_out: Path | None,
    keep_intermediate: bool,
    force: bool,
) -> Path:
    """
    Run a single-input chain (1 input → 1 output). Intermediate stage outputs
    land in the input's directory when keep_intermediate, else in a temp dir.
    """
    print(f"📄 {input_path.name}", file=sys.stderr)

    if keep_intermediate:
        workdir = input_path.parent
        tmp_ctx = None
    else:
        tmp_ctx = tempfile.TemporaryDirectory()
        workdir = Path(tmp_ctx.name)

    try:
        current = input_path
        last_output: Path = current
        for i, stage in enumerate(chain):
            is_last = (i == len(chain) - 1)
            t0 = time.time()
            print(f"   → {stage.name}", file=sys.stderr)
            opts = stage_opts.get(stage.name, {})

            # Stage writes to workdir with its natural filename. We rename
            # afterward only if this is the last stage and the caller passed
            # an explicit --out, or if the desired path collides.
            produced = stage.fn(current, opts, workdir)

            if is_last:
                desired = final_out if final_out else (input_path.parent / produced.name)
                target = _resolve_output_path(desired, force)
                if produced != target:
                    produced.replace(target)
                    produced = target
            else:
                # Intermediate: if it landed in workdir matching an existing
                # file in input's dir (keep_intermediate=True case), resolve
                # the collision so we don't clobber.
                if keep_intermediate:
                    target = _resolve_output_path(produced, force)
                    if produced != target:
                        produced.replace(target)
                        produced = target

            dt = time.time() - t0
            print(f"   ✅ {produced.name}  ({dt:.1f}s)", file=sys.stderr)
            current = produced
            last_output = produced

        return last_output
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


def _run_multi_chain(
    input_paths: list[Path],
    chain: list[Stage],
    stage_opts: dict[str, dict],
    final_out: Path | None,
    keep_intermediate: bool,
    force: bool,
) -> Path:
    """
    Run a chain whose first stage is multi_input (N → 1). After the first
    stage produces a single output, the rest of the chain runs single-input.
    """
    first = chain[0]
    print(f"📚 {len(input_paths)} files → {first.dst}", file=sys.stderr)

    base_dir = input_paths[0].parent
    if keep_intermediate:
        workdir = base_dir
        tmp_ctx = None
    else:
        tmp_ctx = tempfile.TemporaryDirectory()
        workdir = Path(tmp_ctx.name)

    try:
        opts = stage_opts.get(first.name, {})
        t0 = time.time()
        print(f"   → {first.name}", file=sys.stderr)
        produced = first.fn(input_paths, opts, workdir)

        is_last = (len(chain) == 1)
        if is_last:
            desired = final_out if final_out else (base_dir / produced.name)
            target = _resolve_output_path(desired, force)
            if produced != target:
                produced.replace(target)
                produced = target
        elif keep_intermediate:
            target = _resolve_output_path(produced, force)
            if produced != target:
                produced.replace(target)
                produced = target

        dt = time.time() - t0
        print(f"   ✅ {produced.name}  ({dt:.1f}s)", file=sys.stderr)

        # Remaining stages run single-input from the merged output
        if len(chain) > 1:
            return _run_single_chain(
                produced, chain[1:], stage_opts, final_out,
                keep_intermediate, force,
            )
        return produced
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


# ─── Introspection ────────────────────────────────────────────────────────────

def _introspection_payload() -> dict:
    formats: set[str] = set()
    edges_out = []
    for stage in STAGES.values():
        formats.add(stage.src)
        formats.add(stage.dst)
        edges_out.append({
            "from": stage.src,
            "to": stage.dst,
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
    return {
        "formats": sorted(formats),
        "edges": edges_out,
        "version": 2,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="docpipe",
        description="Unified document conversion pipeline.",
    )

    all_formats = sorted({s.src for s in STAGES.values()} |
                         {s.dst for s in STAGES.values()})

    p.add_argument("--from", dest="src", choices=all_formats,
                   help="Source format")
    p.add_argument("--to", dest="dst", choices=all_formats,
                   help="Destination format")
    p.add_argument("--out", type=Path, default=None,
                   help="Explicit output path (invalid with multiple inputs in N→N batches)")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing output files instead of incrementing")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the resolved chain and exit without executing")
    p.add_argument("--introspect", action="store_true",
                   help="Emit the conversion graph + stage options as JSON")

    # Default keep_intermediate=True; --no-keep-intermediate flips it off
    p.add_argument("--keep-intermediate", dest="keep_intermediate",
                   action="store_true", default=True,
                   help="Keep intermediate stage outputs alongside input (default)")
    p.add_argument("--no-keep-intermediate", dest="keep_intermediate",
                   action="store_false",
                   help="Delete intermediate stage outputs after run")

    # Per-stage namespaced options
    for stage in STAGES.values():
        for opt in stage.options:
            p.add_argument(
                f"{stage.flag_prefix}-{opt.name}",
                choices=opt.choices,
                default=opt.default,
                help=opt.help,
            )

    p.add_argument("input", nargs="*", type=Path,
                   help="One or more input files")
    return p


def _collect_stage_opts(args: argparse.Namespace) -> dict[str, dict]:
    """Pull stage-namespaced flags out of the parsed args into per-stage dicts."""
    out: dict[str, dict] = {}
    for stage in STAGES.values():
        out[stage.name] = {}
        for opt in stage.options:
            attr = f"{stage.src}_{opt.name}".replace("-", "_")
            if hasattr(args, attr):
                out[stage.name][opt.name] = getattr(args, attr)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.introspect:
        print(json.dumps(_introspection_payload(), indent=2))
        return 0

    if not args.src or not args.dst:
        parser.error("--from and --to are required (unless --introspect)")
    if not args.input:
        parser.error("at least one input file is required")

    # Validate inputs
    for ip in args.input:
        if not ip.exists():
            print(f"❌ Input not found: {ip}", file=sys.stderr)
            return 1

    # Resolve chain
    try:
        chain = route(args.src, args.dst)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    stage_opts = _collect_stage_opts(args)

    if args.dry_run:
        print(f"Chain: {args.src} → {args.dst}")
        for stage in chain:
            print(f"  {stage.name}  {stage_opts.get(stage.name, {})}")
        for ip in args.input:
            print(f"Input:  {ip}")
        return 0

    first_is_multi = chain[0].multi_input

    # --out is valid only when output is genuinely 1 file:
    #  - single input + single-input chain
    #  - any number of inputs + multi-input first stage (N→1)
    if args.out and len(args.input) > 1 and not first_is_multi:
        print("❌ --out is invalid when batching multiple inputs through a "
              "single-input chain (each input produces its own output).",
              file=sys.stderr)
        return 1

    failed = 0
    final_paths: list[Path] = []

    try:
        if first_is_multi:
            # N → 1: all inputs feed the first stage at once
            out = _run_multi_chain(
                args.input, chain, stage_opts, args.out,
                args.keep_intermediate, args.force,
            )
            final_paths.append(out)
        else:
            # N → N: loop, each input runs independently
            for ip in args.input:
                try:
                    out = _run_single_chain(
                        ip, chain, stage_opts, args.out,
                        args.keep_intermediate, args.force,
                    )
                    final_paths.append(out)
                except Exception as e:
                    print(f"   ❌ failed: {e}", file=sys.stderr)
                    failed += 1
    except Exception as e:
        print(f"❌ Fatal: {e}", file=sys.stderr)
        return 2

    # Emit final paths to stdout (one per line) for caller capture
    for p in final_paths:
        print(p)

    # Summary on stderr when batching
    total = len(args.input) if not first_is_multi else 1
    if total > 1 or failed:
        ok = len(final_paths)
        print(f"── {ok} ok, {failed} failed", file=sys.stderr)

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
