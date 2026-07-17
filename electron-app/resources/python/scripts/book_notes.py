#!/usr/bin/env python3
"""Book Notes scaffold generator for Heelworks.

Creates an Obsidian-ready book workspace from an existing base book note.
This script does not parse books, split PDFs, call AI, or generate content.
It creates the value structure: chapter note shells plus AI handoff files.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path


DEFAULT_OUT_ROOT = Path.home() / "Documents" / "Vault Management"
DEFAULT_VAULT_PATH = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "iCloud~md~obsidian"
    / "Documents"
    / "CAWC Vaulting"
)


class UserAbort(Exception):
    pass


def prompt(text: str) -> str:
    try:
        value = input(text)
    except KeyboardInterrupt as exc:
        print()
        raise UserAbort() from exc
    if value.strip().lower() == "b":
        raise UserAbort()
    return value


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return cleaned or "book"


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\\\|?*]+', "", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "Untitled"


def parse_simple_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}

    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        value = raw.strip().strip('"').strip("'")
        if value:
            meta[key.strip().lower()] = value
    return meta


def infer_book_title(base_note: Path, explicit: str = "") -> str:
    if explicit:
        return explicit.strip()
    meta = parse_simple_frontmatter(base_note)
    for key in ("title", "book", "name"):
        if meta.get(key):
            return meta[key]
    stem = base_note.stem
    return stem[1:] if stem.startswith("_") else stem


def infer_author(base_note: Path, explicit: str = "") -> str:
    if explicit:
        return explicit.strip()
    meta = parse_simple_frontmatter(base_note)
    for key in ("author", "authors"):
        if meta.get(key):
            return meta[key]
    return ""


def parse_chapters_from_text(text: str) -> list[str]:
    chapters: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(?:chapter\s*)?\d+[\).\:\-\s]+", "", line, flags=re.I)
        line = re.sub(r"^\s*[-*]\s+", "", line)
        chapters.append(line.strip() or f"Chapter {len(chapters) + 1}")
    return chapters


def chapters_from_count(count: int) -> list[str]:
    if count <= 0:
        raise ValueError("Chapter count must be greater than zero")
    return [f"Chapter {i}" for i in range(1, count + 1)]


def chapter_note_content(book_title: str, hub_name: str, author: str, number: int, title: str) -> str:
    today = date.today().isoformat()
    chapter_heading = f"Chapter {number} — {title}"
    author_line = f'author: "{author}"\n' if author else ""
    return f"""---
type: book-chapter-note
book: "[[{hub_name}]]"
book_title: "{book_title}"
{author_line}chapter_number: {number}
chapter_title: "{title}"
status: ai-draft-needed
created: {today}
---

# {chapter_heading}

> Source book: [[{hub_name}]]

## AI Workflow

- [ ] Chapter source prepared or split
- [ ] Chapter source uploaded to AI agent
- [ ] AI draft generated
- [ ] Human review complete
- [ ] Final note integrated into vault

## Summary



## Key Ideas



## Important Quotes



## Connections to Existing Notes



## Questions



## Follow-up Links


"""


def upload_checklist_content(book_title: str) -> str:
    return f"""# Chapter Upload Checklist — {book_title}

For each chapter:

1. Open the matching chapter source file created by your PDF split/book workflow.
2. Upload or paste `chapter-notes-agent.md` into your AI assistant.
3. Upload `vault-files.txt` when the agent needs awareness of existing vault notes.
4. Upload the chapter source for the chapter you are working on.
5. Ask the agent to draft notes for that chapter only.
6. Review the output.
7. Paste the reviewed output into the matching chapter note in `Chapters/`.
8. Update the chapter note status from `ai-draft-needed` to `reviewed` or `integrated`.

Heelworks does not generate, review, or save AI-written content automatically.
"""


def agent_instructions_content(book_title: str) -> str:
    return f"""# Chapter Notes Agent

You are helping create chapter notes for `{book_title}`.

Use the uploaded chapter source and produce structured notes that can be pasted
into the matching Obsidian chapter note.

Expected sections:

- Summary
- Key Ideas
- Important Quotes
- Connections to Existing Notes
- Questions
- Follow-up Links

Do not invent citations. If page numbers or locations are unavailable, say so.
Prefer concise, reviewable notes over exhaustive summaries.
"""


def book_context_content(book_title: str, hub_name: str, author: str, chapter_files: list[str]) -> str:
    author_line = f"\nAuthor: {author}" if author else ""
    links = "\n".join(f"- [[{Path(name).stem}]]" for name in chapter_files)
    return f"""# Book Context

Book: [[{hub_name}]]
Title: {book_title}{author_line}

## Chapter Notes

{links}

## Workflow

Use this workspace as the destination for reviewed AI-generated chapter notes.
Create or split chapter source files separately, then work chapter-by-chapter
with the external AI agent.
"""


def generate_vault_files(vault_path: Path, output_path: Path) -> None:
    """Write a plain list of vault markdown files for AI handoff context.

    Mirrors the existing manage_vault behavior: recursively list .md files.
    If the vault is unavailable, write a warning file instead of failing the
    whole scaffold operation.
    """
    vault_path = vault_path.expanduser()
    if not vault_path.exists():
        output_path.write_text(
            f"Vault path not found: {vault_path}\n",
            encoding="utf-8",
        )
        return

    files = sorted(vault_path.rglob("*.md"))
    lines = [str(path) + "\n" for path in files]
    output_path.write_text("".join(lines), encoding="utf-8")


def create_workspace(
    base_note: Path,
    dest: Path | None,
    chapters: list[str],
    title: str = "",
    author: str = "",
    force: bool = False,
) -> Path:
    base_note = base_note.expanduser().resolve()
    if not base_note.exists():
        raise FileNotFoundError(f"Base note not found: {base_note}")
    if base_note.suffix.lower() != ".md":
        raise ValueError(f"Base note must be a .md file: {base_note}")
    if not chapters:
        raise ValueError("At least one chapter is required")

    book_title = infer_book_title(base_note, title)
    book_author = infer_author(base_note, author)
    hub_name = f"_{safe_filename(book_title)}"

    out_dir = dest.expanduser().resolve() if dest else (DEFAULT_OUT_ROOT / slugify(book_title)).resolve()
    chapters_dir = out_dir / "Chapters"
    ai_dir = out_dir / "AI Working"

    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise FileExistsError(f"Output folder already exists and is not empty: {out_dir}")

    chapters_dir.mkdir(parents=True, exist_ok=True)
    ai_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(base_note, out_dir / f"{hub_name}.md")

    chapter_files: list[str] = []
    for idx, chapter_title in enumerate(chapters, 1):
        filename = f"{idx:02d} - {safe_filename(chapter_title)}.md"
        chapter_files.append(filename)
        target = chapters_dir / filename
        target.write_text(
            chapter_note_content(book_title, hub_name, book_author, idx, chapter_title),
            encoding="utf-8",
        )

    (ai_dir / "chapter-notes-agent.md").write_text(agent_instructions_content(book_title), encoding="utf-8")
    (ai_dir / "upload-checklist.md").write_text(upload_checklist_content(book_title), encoding="utf-8")
    (ai_dir / "book-context.md").write_text(
        book_context_content(book_title, hub_name, book_author, chapter_files),
        encoding="utf-8",
    )
    generate_vault_files(DEFAULT_VAULT_PATH, ai_dir / "vault-files.txt")

    print(f"Created Book Notes workspace: {out_dir}")
    print(f"Book: {book_title}")
    if book_author:
        print(f"Author: {book_author}")
    print(f"Chapters: {len(chapters)}")
    print()
    print("Next steps:")
    print("  1. Split/prepare chapter source files separately if needed.")
    print("  2. Open AI Working/upload-checklist.md.")
    print("  3. Work chapter-by-chapter with your external AI assistant.")

    return out_dir


def interactive_create() -> int:
    print("\nBook Notes Workspace Builder")
    print("Type 'b' at any prompt to go back/abort.\n")

    base_raw = prompt("Base book note (.md): ").strip()
    base_note = Path(base_raw).expanduser()

    inferred_title = infer_book_title(base_note) if base_note.exists() else base_note.stem
    title = prompt(f"Book title [{inferred_title}]: ").strip() or inferred_title

    inferred_author = infer_author(base_note) if base_note.exists() else ""
    author_prompt = f"Author [{inferred_author}]: " if inferred_author else "Author (optional): "
    author = prompt(author_prompt).strip() or inferred_author

    default_dest = DEFAULT_OUT_ROOT / slugify(title)
    dest_raw = prompt(f"Destination folder [{default_dest}]: ").strip()
    dest = Path(dest_raw).expanduser() if dest_raw else default_dest

    print("\nChapter input:")
    print("  1. Enter chapter count")
    print("  2. Paste chapter titles, one per line")
    mode = prompt("Select [1-2]: ").strip()

    if mode == "1":
        count = int(prompt("Chapter count: ").strip())
        chapters = chapters_from_count(count)
    elif mode == "2":
        print("\nPaste chapter titles. End with a blank line.")
        lines = []
        while True:
            line = prompt("> ")
            if not line.strip():
                break
            lines.append(line)
        chapters = parse_chapters_from_text("\n".join(lines))
    else:
        print("Invalid selection.")
        return 1

    print("\nPlanned output:")
    print(f"  Base note: {base_note}")
    print(f"  Folder:    {dest}")
    print(f"  Chapters:  {len(chapters)}")
    confirm = prompt("Create workspace? [y/n]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return 1

    create_workspace(base_note, dest, chapters, title=title, author=author, force=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create Obsidian book chapter note scaffolding.")
    sub = parser.add_subparsers(dest="command")

    create = sub.add_parser("create", help="Create a book notes workspace non-interactively")
    create.add_argument("--base-note", required=True, help="Existing base book note .md")
    create.add_argument("--dest", default="", help="Destination folder; defaults under ~/Documents/Vault Management")
    create.add_argument("--title", default="", help="Book title override")
    create.add_argument("--author", default="", help="Author override")
    create.add_argument("--chapter-count", type=int, default=0, help="Generate generic Chapter N titles")
    create.add_argument("--chapters", default="", help="Inline chapter titles, one per line")
    create.add_argument("--chapters-file", default="", help="Text file with one chapter title per line")
    create.add_argument("--force", action="store_true", help="Allow writing into a non-empty output folder")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "create":
        if args.chapters:
            chapters = parse_chapters_from_text(args.chapters)
        elif args.chapters_file:
            chapters = parse_chapters_from_text(Path(args.chapters_file).read_text(encoding="utf-8"))
        elif args.chapter_count:
            chapters = chapters_from_count(args.chapter_count)
        else:
            parser.error("create requires --chapter-count, --chapters, or --chapters-file")

        dest = Path(args.dest) if args.dest else None
        try:
            create_workspace(
                Path(args.base_note),
                dest,
                chapters,
                title=args.title,
                author=args.author,
                force=args.force,
            )
            return 0
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    try:
        return interactive_create()
    except UserAbort:
        print("\nAborted.")
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
