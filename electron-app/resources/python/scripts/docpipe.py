#!/usr/bin/env python3
"""
docpipe — Unified document operation pipeline.

Single entry point for all document operations. Operations are registered in
OPERATIONS. Each operation declares input/output format + arity. Named
pipelines in PIPELINES chain operations explicitly.

Add a new operation:
  1. Write a function: op_<name>(inputs, options, output_path) -> Path | list[Path]
  2. Register it in OPERATIONS with its options schema and arities.

The CLI auto-discovers everything from OPERATIONS — no other code changes.

Arities:
  Input:  "one"  → single file (default)
          "many" → list of files (e.g. images_to_pdf, pdf_merge)
  Output: "one"  → single file (default)
          "many" → list of files (e.g. pdf_split)

CLI:
  docpipe pdf_to_txt input.pdf
  docpipe pdf_to_txt a.pdf b.pdf c.pdf                # batch: N→N
  docpipe pdf_to_txt input.pdf --pdf_to_txt-layout plain
  docpipe images_to_pdf img1.png img2.png --out combined.pdf
  docpipe pptx_to_pdf deck.pptx --pptx_to_pdf-compress medium
  docpipe --chain pptx_to_pdf,pdf_to_txt deck.pptx    # explicit chain
  docpipe pptx_to_txt deck.pptx                       # named pipeline
  docpipe --list                                      # list operations
  docpipe --introspect                                # JSON metadata
  docpipe --dry-run ...
  docpipe --echo ...
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import zlib

import pikepdf
import pymupdf  # PyMuPDF >= 1.24
from PIL import Image


# ─── Types ────────────────────────────────────────────────────────────────────

OpFn = Callable[..., Any]


@dataclass
class OpOption:
    name: str
    choices: list[str]
    default: str
    help: str = ""


@dataclass
class Operation:
    name: str               # unique, e.g. "pdf_to_txt"
    src: str                # source format
    dst: str                # destination format
    fn: OpFn
    input_arity: str = "one"   # "one" | "many"
    output_arity: str = "one"  # "one" | "many"
    options: list[OpOption] = field(default_factory=list)
    description: str = ""
    output_suffix: str = ""    # if set: {stem}{suffix}.{ext} + always overwrite


# ─── Format → recognized extensions ───────────────────────────────────────────

FORMAT_EXTENSIONS: dict[str, set[str]] = {
    "pdf":    {".pdf"},
    "txt":    {".txt"},
    "md":     {".md", ".markdown"},
    "images": {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"},
    "pptx":   {".pptx"},
    "docx":   {".docx"},
    "json":   {".json"},
}


# ─── Layout reconstruction (for pdf_to_txt layout mode) ───────────────────────

_CHAR_WIDTH_PT = 6.0
_ROW_TOL_PT    = 3.0


def _layout_page_text(page) -> str:
    """Reconstruct text with column/table alignment via block-binning."""
    blocks = page.get_text("blocks")
    lines: list[tuple[float, float, float, float, str]] = []

    for b in blocks:
        if len(b) < 7 or b[6] != 0:
            continue
        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
        text = text.rstrip("\n")
        if not text.strip():
            continue
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

    min_x = min(l[0] for l in lines)
    if min_x > 0:
        lines = [(x0 - min_x, y0, x1, y1, t) for (x0, y0, x1, y1, t) in lines]

    lines.sort(key=lambda l: (l[1], l[0]))

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


# ─── Operation: pdf_to_txt ────────────────────────────────────────────────────

def op_pdf_to_txt(input_path: Path, opts: dict, output_path: Path) -> Path:
    """Extract text from a PDF. Options: layout (default) or plain."""
    mode = opts.get("layout", "layout")

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


# ─── Operation: images_to_pdf ─────────────────────────────────────────────────

_PAGE_SIZES_PT: dict[str, tuple[float, float]] = {
    "letter": (612.0, 792.0),
    "a4":     (595.0, 842.0),
}


def op_images_to_pdf(inputs: list[Path], opts: dict, output_path: Path) -> Path:
    """Combine images into a single PDF. Multi-input: N images → 1 PDF."""
    page_size = opts.get("page_size", "auto")

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
                    if (img_w > img_h) != (pw > ph):
                        pw, ph = ph, pw

                new_page = out_doc.new_page(width=pw, height=ph)

                if page_size == "auto":
                    new_page.show_pdf_page(new_page.rect, img_pdf, 0)
                else:
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


# ─── Operation: pptx_to_pdf (macOS, via PowerPoint AppleScript) ───────────────

_PPTX_LAUNCHED_BY_US = False


def _powerpoint_is_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-x", "Microsoft PowerPoint"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _quit_powerpoint_if_we_launched_it():
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


_DPI_PRESETS: dict[str, int | None] = {
    "none":   None,
    "small":  72,
    "medium": 150,
    "large":  300,
}


def _parse_content_stream_ctms(page) -> dict[str, tuple[float, float]]:
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
    pdf = pikepdf.open(pdf_path, allow_overwriting_input=True)
    processed: set[int] = set()
    n_resized = 0

    try:
        for page in pdf.pages:
            try:
                ctms = _parse_content_stream_ctms(page)
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


def op_pptx_to_pdf(input_path: Path, opts: dict, output_path: Path) -> Path:
    """Convert PPTX to PDF using PowerPoint via AppleScript (macOS only)."""
    global _PPTX_LAUNCHED_BY_US

    if platform.system() != "Darwin":
        raise RuntimeError(
            "pptx_to_pdf requires macOS + Microsoft PowerPoint."
        )

    compress = opts.get("compress", "medium")
    if compress not in _DPI_PRESETS:
        raise ValueError(f"Unknown --pptx_to_pdf-compress value: {compress!r}")

    if not _PPTX_LAUNCHED_BY_US and not _powerpoint_is_running():
        _PPTX_LAUNCHED_BY_US = True

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

    dpi = _DPI_PRESETS[compress]
    if dpi is not None:
        try:
            _downsample_pdf_images(output_path, dpi)
        except Exception as e:
            print(f"⚠️  Image downsampling failed ({e}); keeping uncompressed PDF", file=sys.stderr)

    return output_path



# ─── Operation: pdf_merge ─────────────────────────────────────────────────────

def op_pdf_merge(inputs: list[Path], opts: dict, output_path: Path) -> Path:
    """Merge N PDFs into one. Multi-input: N PDFs → 1 PDF.
    Options:
      bookmarks: 'yes' (default) creates a top-level bookmark per source file,
                 named after the file stem. 'no' = raw concatenation.
    """
    bookmarks = opts.get("bookmarks", "yes") == "yes"

    out_doc = pymupdf.open()
    toc: list[list] = []  # [[level, title, page], ...]
    metadata_source = None

    try:
        for src_path in inputs:
            src_doc = pymupdf.open(src_path)
            try:
                # Bookmark points at the page where this file starts
                start_page = out_doc.page_count
                if metadata_source is None:
                    # Capture metadata from first file for the merged output
                    metadata_source = dict(src_doc.metadata or {})
                out_doc.insert_pdf(src_doc)
                if bookmarks:
                    # pymupdf TOC uses 1-indexed page numbers
                    toc.append([1, src_path.stem, start_page + 1])
            finally:
                src_doc.close()

        if bookmarks and toc:
            out_doc.set_toc(toc)
        if metadata_source:
            # Preserve first file's metadata in the merged output
            out_doc.set_metadata(metadata_source)

        out_doc.save(output_path, garbage=4, deflate=True)
    finally:
        out_doc.close()

    return output_path



# ─── Operation: pdf_strip (metadata removal) ──────────────────────────────────

def op_pdf_strip(input_path: Path, opts: dict, output_path: Path) -> Path:
    """Strip all identifying metadata from a PDF.

    Removes:
      - /Info dictionary    (author, title, producer, creation/mod dates, keywords)
      - /Metadata XMP stream (what Adobe Acrobat and modern viewers display)

    Preserves:
      - /ID trailer hash    (pikepdf regenerates on save; the hash contains
                            no recoverable human-readable information — it
                            is solely a document fingerprint for spec compliance)

    Result: File → Properties shows clean metadata in any viewer.
    """
    pdf = pikepdf.open(input_path)
    try:
        # /Info dictionary
        if pdf.docinfo is not None:
            for key in list(pdf.docinfo.keys()):
                del pdf.docinfo[key]

        # /Metadata XMP stream — drop the reference from Root entirely
        if "/Metadata" in pdf.Root:
            del pdf.Root["/Metadata"]

        pdf.save(output_path)
    finally:
        pdf.close()

    return output_path



# ─── Operation: pdf_bookmark_add ──────────────────────────────────────────────

def _parse_bookmark_list(raw: str, page_count: int) -> list[tuple[int, str]]:
    """Parse the textarea input into [(page_1indexed, title), ...].

    Format: one entry per line, "page:title".
      - Blank lines ignored.
      - Lines starting with # are comments, ignored.
      - First colon is the separator; rest of line is the title.
      - Page numbers must be 1..page_count; rejected otherwise.
      - Duplicates allowed (PDF spec doesn't forbid).
    """
    out: list[tuple[int, str]] = []
    for lineno, raw_line in enumerate(raw.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Line {lineno}: missing ':' separator → {raw_line!r}")
        page_str, title = line.split(":", 1)
        try:
            page = int(page_str.strip())
        except ValueError:
            raise ValueError(f"Line {lineno}: page is not a number → {raw_line!r}")
        title = title.strip()
        if not title:
            raise ValueError(f"Line {lineno}: empty title → {raw_line!r}")
        if not 1 <= page <= page_count:
            raise ValueError(
                f"Line {lineno}: page {page} out of range (PDF has {page_count} pages)"
            )
        out.append((page, title))
    if not out:
        raise ValueError("No bookmark entries provided.")
    return out


def op_pdf_bookmark_add(input_path: Path, opts: dict, output_path: Path) -> Path:
    """Add bookmarks to a PDF from a plain-text list of 'page:title' lines."""
    raw = opts.get("list", "")
    if not raw.strip():
        raise ValueError("Bookmark list is empty. Provide page:title lines.")

    doc = pymupdf.open(input_path)
    try:
        entries = _parse_bookmark_list(raw, doc.page_count)
        # pymupdf TOC format: [[level, title, page_1indexed], ...]
        toc = [[1, title, page] for page, title in entries]
        doc.set_toc(toc)
        doc.save(output_path, garbage=4, deflate=True)
    finally:
        doc.close()
    return output_path


# ─── Operation: pdf_bookmark_analyze ─────────────────────────────────────────

def _detect_title_font(doc, sample_pages: int = 30):
    """Find dominant title font signature: (size_pt, is_bold) or None."""
    from collections import Counter
    n_pages = min(sample_pages, doc.page_count)
    largest_per_page = []

    for i in range(n_pages):
        page = doc[i]
        try:
            blocks = page.get_text("dict")["blocks"]
        except Exception:
            continue
        candidates = []
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if len(text) < 3:
                        continue
                    size = round(span["size"], 1)
                    is_bold = bool(span["flags"] & 16)
                    candidates.append((size, is_bold, text))
        if not candidates:
            continue
        candidates.sort(key=lambda c: (-c[0], not c[1]))
        size, is_bold, _ = candidates[0]
        largest_per_page.append((size, is_bold))

    if not largest_per_page:
        return None

    counts = Counter(largest_per_page)
    threshold = max(1, int(0.4 * len(largest_per_page)))
    candidates = [(size, bold, n) for (size, bold), n in counts.items() if n >= threshold]
    if not candidates:
        (size, bold), _ = counts.most_common(1)[0]
        return (size, bold)
    candidates.sort(key=lambda c: (-c[0], not c[1]))
    size, bold, _ = candidates[0]
    return (size, bold)


def _clean_title(text: str) -> str:
    """Normalize a detected title."""
    import re as _re
    text = " ".join(text.split())
    text = _re.sub(r"^(Chapter|Slide|Section|Part)\s+\d+[:.\s]*", "", text, flags=_re.I)
    text = _re.sub(r"^\d+[:.\s]+", "", text)
    return text.strip()


def op_pdf_bookmark_analyze(input_path: Path, opts: dict, output_path: Path) -> Path:
    """Analyze a PDF and propose bookmarks.

    Strategy order:
      1. If PDF has embedded /Outlines, use those
      2. Else try font-signature detection on slide-deck-style content
      3. Else return empty proposal with explanation

    Output: JSON to stdout (output_path is unused but required by runner).
      {
        "source": "outlines" | "fonts" | "none",
        "entries": [[page_1indexed, title], ...],
        "info": "human-readable note for UI display"
      }
    """
    doc = pymupdf.open(input_path)
    result = {"source": "none", "entries": [], "info": ""}

    try:
        # Strategy 1: embedded outlines
        toc = doc.get_toc(simple=True)
        if toc:
            entries = [[page, title] for level, title, page in toc]
            result["source"] = "outlines"
            result["entries"] = entries
            result["info"] = f"Embedded outlines ({len(entries)} entries)"
        else:
            # Strategy 2: font detection
            title_font = _detect_title_font(doc)
            if title_font is None:
                result["info"] = (
                    "No embedded outlines and no consistent title font detected. "
                    "Type bookmarks manually below as 'page:title' per line."
                )
            else:
                target_size, target_bold = title_font
                entries = []
                for i in range(doc.page_count):
                    page = doc[i]
                    try:
                        blocks = page.get_text("dict")["blocks"]
                    except Exception:
                        continue
                    title_parts = []
                    for block in blocks:
                        if "lines" not in block:
                            continue
                        for line in block["lines"]:
                            for span in line["spans"]:
                                size = round(span["size"], 1)
                                is_bold = bool(span["flags"] & 16)
                                if abs(size - target_size) < 0.5 and is_bold == target_bold:
                                    text = span["text"].strip()
                                    if text and len(text) >= 2:
                                        title_parts.append(text)
                    if not title_parts:
                        continue
                    title = _clean_title(" ".join(title_parts))
                    if not title or len(title) < 3:
                        continue
                    entries.append([i + 1, title])

                if entries:
                    result["source"] = "fonts"
                    result["entries"] = entries
                    weight = "bold" if target_bold else "regular"
                    result["info"] = (
                        f"Font detection ({target_size}pt {weight}, "
                        f"{len(entries)} entries). Review and edit before applying."
                    )
                else:
                    result["info"] = (
                        f"Font signature detected ({target_size}pt) but no titles "
                        "extracted. Type bookmarks manually below."
                    )
    finally:
        doc.close()

    # JSON to stdout for UI consumption
    print(json.dumps(result, ensure_ascii=False))
    return output_path



# ─── Operation: pdf_split ─────────────────────────────────────────────────────

def _sanitize_filename(title: str, max_len: int = 60) -> str:
    """Replace filesystem-hostile chars, collapse whitespace, cap length."""
    import re as _re
    cleaned = _re.sub(r'[/\\:*?"<>|]', "_", title)
    cleaned = _re.sub(r"\s+", "_", cleaned).strip("_")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("_")
    return cleaned or "untitled"


def _parse_page_ranges(spec: str, page_count: int) -> list[tuple[int, int]]:
    """Parse '1-12, 13-24, 25-end' or '25-' into [(start, end), ...] 1-indexed inclusive."""
    if not spec.strip():
        raise ValueError("Page range spec is empty.")
    ranges: list[tuple[int, int]] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" not in chunk:
            # single page
            try:
                p = int(chunk)
            except ValueError:
                raise ValueError(f"Invalid page spec: {chunk!r}")
            if not 1 <= p <= page_count:
                raise ValueError(f"Page {p} out of range (PDF has {page_count} pages)")
            ranges.append((p, p))
            continue
        a, b = chunk.split("-", 1)
        a = a.strip()
        b = b.strip()
        try:
            start = int(a) if a else 1
        except ValueError:
            raise ValueError(f"Invalid start page: {a!r}")
        if not b or b.lower() == "end":
            end = page_count
        else:
            try:
                end = int(b)
            except ValueError:
                raise ValueError(f"Invalid end page: {b!r}")
        if start < 1 or end > page_count or start > end:
            raise ValueError(
                f"Range {start}-{end} invalid (PDF has {page_count} pages)"
            )
        ranges.append((start, end))
    if not ranges:
        raise ValueError("No valid ranges parsed.")
    return ranges


def _split_audit(
    audit_path: Path,
    source_name: str,
    mode: str,
    page_count: int,
    chunks: list[tuple[int, int, Path]],
    extra_notes: list[str] | None = None,
) -> None:
    """Write the split audit trail."""
    lines = [
        f"# Split audit for: {source_name}",
        f"# Mode: {mode}",
        f"# Source pages: 1-{page_count}",
        f"# Produced: {len(chunks)} files",
        "",
    ]
    if extra_notes:
        for note in extra_notes:
            lines.append(f"# {note}")
        lines.append("")
    for i, (start, end, out_path) in enumerate(chunks, 1):
        if start == end:
            page_label = f"page {start}"
        else:
            page_label = f"pages {start}-{end}"
        lines.append(f"{i:02d}. {page_label:20s} →  {out_path.name}")
    audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def op_pdf_split(input_path: Path, opts: dict, output_path: Path) -> list[Path]:
    """Split a PDF into multiple files by mode.

    Modes:
      range    — split at user-specified page ranges (e.g. "1-12, 13-24, 25-end")
      every    — split into uniform chunks of N pages
      bookmark — split at each top-level bookmark boundary

    output_path is the resolved output directory + stem base (runner-managed).
    Returns list of produced file paths.
    """
    mode = opts.get("mode", "range")
    out_dir = output_path.parent
    stem = input_path.stem

    doc = pymupdf.open(input_path)
    try:
        page_count = doc.page_count

        # Resolve chunks: list of (start_1idx, end_1idx, suffix_label)
        chunks: list[tuple[int, int, str]] = []
        extra_notes: list[str] = []

        if mode == "range":
            spec = opts.get("ranges", "")
            ranges = _parse_page_ranges(spec, page_count)
            for start, end in ranges:
                label = f"p{start}-{end}"
                chunks.append((start, end, label))

        elif mode == "every":
            n_str = opts.get("every", "10")
            try:
                n = int(n_str)
            except ValueError:
                raise ValueError(f"--pdf_split-every must be an integer, got {n_str!r}")
            if n < 1:
                raise ValueError("Pages-per-chunk must be ≥ 1")
            start = 1
            while start <= page_count:
                end = min(start + n - 1, page_count)
                label = f"p{start}-{end}"
                chunks.append((start, end, label))
                start = end + 1

        elif mode == "bookmark":
            toc = doc.get_toc(simple=True)  # [[level, title, page_1idx], ...]
            # Only top-level bookmarks for split boundaries
            top_level = [(title, page) for level, title, page in toc if level == 1]
            if not top_level:
                raise RuntimeError(
                    f"{input_path.name} has no top-level bookmarks. "
                    "Use Range or Every-N mode, or run PDF Bookmarks first."
                )
            # Build chunks: each bookmark starts a chunk; chunk ends at next bookmark - 1
            first_bm_page = top_level[0][1]
            if first_bm_page > 1:
                # Pre-bookmark content becomes chunk 00
                label = f"00_Front_Matter"
                chunks.append((1, first_bm_page - 1, label))
                extra_notes.append(
                    f"Pages 1-{first_bm_page - 1} preceded first bookmark; "
                    f"saved as Front_Matter."
                )
            for i, (title, start) in enumerate(top_level):
                if i + 1 < len(top_level):
                    end = top_level[i + 1][1] - 1
                else:
                    end = page_count
                clean = _sanitize_filename(title, max_len=60)
                # Numeric prefix preserves order
                idx = i + 1 if first_bm_page == 1 else i + 2
                label = f"{idx:02d}_{clean}"
                chunks.append((start, end, label))

        else:
            raise ValueError(f"Unknown split mode: {mode!r}")

        # Write each chunk
        produced: list[tuple[int, int, Path]] = []
        for start, end, suffix in chunks:
            out_path = out_dir / f"{stem}_{suffix}.pdf"
            chunk_doc = pymupdf.open()
            try:
                # pymupdf insert_pdf uses 0-indexed inclusive
                chunk_doc.insert_pdf(doc, from_page=start - 1, to_page=end - 1)
                chunk_doc.save(out_path, garbage=4, deflate=True)
            finally:
                chunk_doc.close()
            produced.append((start, end, out_path))

        # Audit trail
        audit_path = out_dir / f"{stem}_split.txt"
        _split_audit(
            audit_path, input_path.name, mode, page_count, produced, extra_notes
        )

        print(
            f"   ✓ {len(produced)} files produced, audit at {audit_path.name}",
            file=sys.stderr,
        )
    finally:
        doc.close()

    return [p[2] for p in produced]


# ─── Operations registry ──────────────────────────────────────────────────────

OPERATIONS: dict[str, Operation] = {
    "pdf_to_txt": Operation(
        name="pdf_to_txt", src="pdf", dst="txt", fn=op_pdf_to_txt,
        description="Extract text from a PDF.",
        options=[
            OpOption(name="layout", choices=["layout", "plain"], default="layout",
                     help="Preserve columns/tables (layout) or extract reading-order text (plain)."),
        ],
    ),
    "images_to_pdf": Operation(
        name="images_to_pdf", src="images", dst="pdf", fn=op_images_to_pdf,
        input_arity="many",
        description="Combine images into a single PDF.",
        options=[
            OpOption(name="page_size", choices=["auto", "letter", "a4"], default="auto",
                     help="auto = page per image; letter/a4 = fixed page with contain-fit."),
        ],
    ),
    "pdf_merge": Operation(
        name="pdf_merge", src="pdf", dst="pdf", fn=op_pdf_merge,
        input_arity="many",
        description="Merge multiple PDFs into one in queue order.",
        options=[
            OpOption(name="bookmarks", choices=["yes", "no"], default="yes",
                     help="Create top-level bookmarks at each source file boundary."),
        ],
    ),
    "pdf_bookmark_analyze": Operation(
        name="pdf_bookmark_analyze", src="pdf", dst="json", fn=op_pdf_bookmark_analyze,
        description="Analyze a PDF and propose bookmarks (outlines or font detection).",
        options=[],
        output_suffix="",
    ),
    "pdf_bookmark_add": Operation(
        name="pdf_bookmark_add", src="pdf", dst="pdf", fn=op_pdf_bookmark_add,
        description="Add bookmarks to a PDF from a 'page:title' list.",
        options=[
            OpOption(name="list", choices=[], default="",
                     help="Plain text, one entry per line: page:title. Blank lines + # comments OK."),
        ],
        output_suffix="_bookmarked",
    ),

    "pdf_split": Operation(
        name="pdf_split", src="pdf", dst="pdf", fn=op_pdf_split,
        output_arity="many",
        description="Split a PDF by range, every N pages, or at bookmarks.",
        options=[
            OpOption(name="mode", choices=["range", "every", "bookmark"], default="bookmark",
                     help="range: explicit page ranges. every: N pages per chunk. bookmark: split at top-level bookmarks."),
            OpOption(name="ranges", choices=[], default="",
                     help="For range mode: comma-separated, e.g. '1-12, 13-24, 25-end'."),
            OpOption(name="every", choices=[], default="10",
                     help="For every mode: pages per chunk."),
        ],
    ),
    "pdf_strip": Operation(
        name="pdf_strip", src="pdf", dst="pdf", fn=op_pdf_strip,
        description="Remove all metadata from a PDF (info dict + XMP + /ID).",
        options=[],
        output_suffix="_stripped",
    ),
    "pptx_to_pdf": Operation(
        name="pptx_to_pdf", src="pptx", dst="pdf", fn=op_pptx_to_pdf,
        description="Convert PPTX to PDF via PowerPoint (macOS).",
        options=[
            OpOption(name="compress", choices=["none", "small", "medium", "large"], default="medium",
                     help="Image quality: none/raw, small/72dpi, medium/150dpi, large/300dpi."),
        ],
    ),
}

# ─── Named pipelines ──────────────────────────────────────────────────────────

PIPELINES: dict[str, list[str]] = {
    "pptx_to_txt": ["pptx_to_pdf", "pdf_to_txt"],
}


# ─── Resolve operation name → list of operations ──────────────────────────────

def resolve_pipeline(name: str) -> list[Operation]:
    """Map a name to a sequence of operations. Pipelines unfold to their ops."""
    if name in OPERATIONS:
        return [OPERATIONS[name]]
    if name in PIPELINES:
        return [OPERATIONS[op_name] for op_name in PIPELINES[name]]
    raise ValueError(
        f"Unknown operation or pipeline: {name!r}.\n"
        f"Available operations: {sorted(OPERATIONS.keys())}\n"
        f"Available pipelines:  {sorted(PIPELINES.keys())}"
    )


def resolve_chain(chain_str: str) -> list[Operation]:
    """Parse --chain op1,op2,op3 into operations."""
    names = [n.strip() for n in chain_str.split(",") if n.strip()]
    return [OPERATIONS[n] for n in names]


# ─── Output naming + intermediate handling ────────────────────────────────────

def resolve_output_path(desired_dir: Path, stem: str, ext: str, force: bool) -> Path:
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
    allowed_exts = FORMAT_EXTENSIONS.get(src_format, set())
    expanded: list[Path] = []
    for raw_path in raw:
        p = Path(raw_path).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"Input not found: {p}")
        if p.is_dir():
            if not allowed_exts:
                raise ValueError(
                    f"Cannot expand directory '{p}': format '{src_format}' has no recognized extensions"
                )
            matches = sorted(
                child for child in p.iterdir()
                if child.is_file() and child.suffix.lower() in allowed_exts
            )
            if not matches:
                raise ValueError(f"No files matching {sorted(allowed_exts)} in directory: {p}")
            expanded.extend(matches)
        else:
            if allowed_exts and p.suffix.lower() not in allowed_exts:
                raise ValueError(
                    f"Input '{p.name}' does not match extensions for format '{src_format}': {sorted(allowed_exts)}"
                )
            expanded.append(p)
    return expanded


# ─── Run a chain on inputs ────────────────────────────────────────────────────

def _run_chain_single(
    input_path: Path,
    chain: list[Operation],
    op_opts: dict[str, dict],
    out_path: Path | None,
    keep_intermediate: bool,
    force: bool,
) -> Path:
    """Chain of single-input ops on one file."""
    print(f"📄 {input_path.name}", file=sys.stderr)

    if keep_intermediate or out_path:
        current = input_path
        for i, op in enumerate(chain):
            is_last = (i == len(chain) - 1)
            if is_last and out_path is not None:
                target_dir = out_path.parent
                target_stem = out_path.stem
                target = resolve_output_path(target_dir, target_stem, op.dst, force)
            elif op.output_suffix:
                # Stable suffix mode: always overwrite, no _1/_2 incrementing
                target_dir = input_path.parent
                target = target_dir / f"{current.stem}{op.output_suffix}.{op.dst}"
            else:
                target_dir = input_path.parent
                target = resolve_output_path(target_dir, current.stem, op.dst, force)

            print(f"   → {op.name}", file=sys.stderr)
            t0 = time.time()
            produced = op.fn(current, op_opts[op.name], target)
            elapsed = time.time() - t0
            if isinstance(produced, list):
                print(f"   ✅ {len(produced)} files produced  ({elapsed:.1f}s)", file=sys.stderr)
                if is_last:
                    return produced
                current = produced[0] if produced else current
            else:
                print(f"   ✅ {produced.name}  ({elapsed:.1f}s)", file=sys.stderr)
                current = produced
        return current
    else:
        with tempfile.TemporaryDirectory(prefix="docpipe_") as td:
            tdpath = Path(td)
            current = input_path
            for i, op in enumerate(chain):
                is_last = (i == len(chain) - 1)
                if is_last:
                    target_dir = (out_path.parent if out_path else input_path.parent)
                    target_stem = (out_path.stem if out_path else current.stem)
                    target = resolve_output_path(target_dir, target_stem, op.dst, force)
                else:
                    target = tdpath / f"{current.stem}.{op.dst}"

                print(f"   → {op.name}", file=sys.stderr)
                t0 = time.time()
                produced = op.fn(current, op_opts[op.name], target)
                elapsed = time.time() - t0
                if isinstance(produced, list):
                    print(f"   ✅ {len(produced)} files produced  ({elapsed:.1f}s)", file=sys.stderr)
                    if is_last:
                        return produced
                    current = produced[0] if produced else current
                else:
                    print(f"   ✅ {produced.name}  ({elapsed:.1f}s)", file=sys.stderr)
                    current = produced
            return current


def _run_chain_multi_first(
    inputs: list[Path],
    chain: list[Operation],
    op_opts: dict[str, dict],
    out_path: Path,
    keep_intermediate: bool,
    force: bool,
) -> Path:
    """Chain whose first op is many-input. Subsequent ops are single-input."""
    print(f"📦 {len(inputs)} inputs → {chain[0].dst}", file=sys.stderr)

    target = resolve_output_path(out_path.parent, out_path.stem, chain[0].dst, force)

    print(f"   → {chain[0].name}", file=sys.stderr)
    t0 = time.time()
    first_out = chain[0].fn(inputs, op_opts[chain[0].name], target)
    elapsed = time.time() - t0
    print(f"   ✅ {first_out.name}  ({elapsed:.1f}s)", file=sys.stderr)

    if len(chain) == 1:
        return first_out

    return _run_chain_single(first_out, chain[1:], op_opts, out_path, keep_intermediate, force)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="docpipe",
        description="Unified document operation pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("operation", nargs="?",
                   help="Operation or pipeline name (use --list to see options).")
    p.add_argument("--chain", default=None,
                   help="Explicit op chain, e.g. --chain pptx_to_pdf,pdf_to_txt")
    p.add_argument("--list", action="store_true",
                   help="List operations and pipelines, then exit.")
    p.add_argument("--out", type=Path, default=None,
                   help="Explicit output path. Required for many-input ops.")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="Directory to write outputs to. Auto-names within.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing outputs.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the resolved chain, then exit.")
    p.add_argument("--introspect", action="store_true",
                   help="Print operations + options as JSON.")
    p.add_argument("--keep-intermediate", dest="keep_intermediate",
                   action="store_true", default=True)
    p.add_argument("--no-keep-intermediate", dest="keep_intermediate",
                   action="store_false")
    p.add_argument("--echo", action="store_true",
                   help="Debug: print argv as JSON and exit.")

    # Per-operation options, namespaced as --{op_name}-{option_name}
    for op in OPERATIONS.values():
        for opt in op.options:
            kwargs = {
                "dest": f"opt_{op.name}_{opt.name}",
                "default": opt.default,
                "help": opt.help,
            }
            if opt.choices:
                kwargs["choices"] = opt.choices
            p.add_argument(f"--{op.name}-{opt.name}", **kwargs)

    p.add_argument("inputs", nargs="*", type=str,
                   help="Input file paths or directories.")
    return p


def list_payload() -> str:
    out: list[str] = ["Operations:"]
    for op in OPERATIONS.values():
        arity = ""
        if op.input_arity == "many":
            arity += " [N inputs]"
        if op.output_arity == "many":
            arity += " [N outputs]"
        out.append(f"  {op.name:20s}  {op.src} → {op.dst}{arity}")
        if op.description:
            out.append(f"    {op.description}")
    if PIPELINES:
        out.append("\nPipelines:")
        for name, ops in PIPELINES.items():
            out.append(f"  {name:20s}  {' → '.join(ops)}")
    return "\n".join(out)


def introspect_payload() -> dict:
    return {
        "formats": sorted(
            set(o.src for o in OPERATIONS.values()) |
            set(o.dst for o in OPERATIONS.values())
        ),
        "operations": [
            {
                "name": op.name,
                "src": op.src,
                "dst": op.dst,
                "input_arity": op.input_arity,
                "output_arity": op.output_arity,
                "description": op.description,
                "extensions": sorted(FORMAT_EXTENSIONS.get(op.src, set())),
                "options": [
                    {
                        "name": opt.name,
                        "flag": f"--{op.name}-{opt.name}",
                        "choices": opt.choices,
                        "default": opt.default,
                        "help": opt.help,
                    }
                    for opt in op.options
                ],
            }
            for op in OPERATIONS.values()
        ],
        "pipelines": {name: ops for name, ops in PIPELINES.items()},
        "version": 4,
    }


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if "--echo" in raw_argv:
        print(json.dumps({"received_argv": raw_argv}, indent=2))
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        print(list_payload())
        return 0

    if args.introspect:
        print(json.dumps(introspect_payload(), indent=2))
        return 0

    try:
        if args.chain:
            chain = resolve_chain(args.chain)
        elif args.operation:
            chain = resolve_pipeline(args.operation)
        else:
            parser.error("operation name or --chain is required (use --list)")
    except (ValueError, KeyError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    if not args.inputs:
        parser.error("at least one input is required")

    op_opts: dict[str, dict] = {}
    for op in chain:
        opts: dict = {}
        for opt in op.options:
            attr = f"opt_{op.name}_{opt.name}"
            opts[opt.name] = getattr(args, attr, opt.default)
        op_opts[op.name] = opts

    first_op = chain[0]
    try:
        inputs = expand_inputs(args.inputs, first_op.src)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    if args.out is not None and args.out_dir is not None:
        print("❌ --out and --out-dir are mutually exclusive", file=sys.stderr)
        return 1

    # Bare --out filename (no directory): resolve against first input's folder.
    # Matches user expectation that "merged.pdf" lands next to the source files,
    # not in the spawning process's cwd (which is the Electron app dir).
    if args.out is not None and args.out.parent == Path("."):
        args.out = inputs[0].parent / args.out.name

    if first_op.input_arity == "many":
        if args.out is None:
            print(
                f"❌ --out is required for many-input operations "
                f"({first_op.name} combines N inputs into 1 output)",
                file=sys.stderr,
            )
            return 1
    else:
        if args.out is not None and len(inputs) > 1:
            print(
                f"❌ --out cannot be used with multiple inputs in a "
                f"{first_op.name} chain (each input produces its own output).",
                file=sys.stderr,
            )
            return 1

    if args.dry_run:
        print("Chain: " + " → ".join([chain[0].src] + [o.dst for o in chain]))
        for op in chain:
            print(f"  {op.name}  {op_opts[op.name]}")
        if first_op.input_arity == "many":
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

    final_outputs: list[Path] = []
    failures: list[tuple[Path, Exception]] = []

    if first_op.input_arity == "many":
        try:
            final = _run_chain_multi_first(
                inputs, chain, op_opts, args.out,
                args.keep_intermediate, args.force,
            )
            final_outputs.append(final)
        except Exception as e:
            print(f"❌ {e}", file=sys.stderr)
            return 2
    else:
        for inp in inputs:
            effective_out = args.out if len(inputs) == 1 else None
            if effective_out is None and args.out_dir is not None:
                last = chain[-1]
                effective_out = args.out_dir / f"{inp.stem}.{last.dst}"
            try:
                final = _run_chain_single(
                    inp, chain, op_opts,
                    effective_out,
                    args.keep_intermediate, args.force,
                )
                if isinstance(final, list):
                    final_outputs.extend(final)
                else:
                    final_outputs.append(final)
            except Exception as e:
                print(f"❌ {inp.name}: {e}", file=sys.stderr)
                failures.append((inp, e))

    for f in final_outputs:
        print(f)

    if len(inputs) > 1 and first_op.input_arity != "many":
        print(f"── {len(final_outputs)} ok, {len(failures)} failed", file=sys.stderr)

    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
