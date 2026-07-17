from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "resources" / "python" / "scripts" / "book_notes.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_notes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_slugify_and_chapter_parsing():
    module = load_module()
    assert module.slugify("Good Strategy / Bad Strategy!") == "good-strategy-bad-strategy"
    assert module.parse_chapters_from_text("1. Intro\n2. The Kernel\n") == ["Intro", "The Kernel"]


def test_create_workspace_from_chapter_count(tmp_path):
    module = load_module()
    base = tmp_path / "_Good Strategy Bad Strategy.md"
    base.write_text("---\ntitle: Good Strategy Bad Strategy\nauthor: Richard Rumelt\n---\n", encoding="utf-8")
    dest = tmp_path / "workspace"

    out = module.create_workspace(
        base,
        dest,
        module.chapters_from_count(2),
        force=True,
    )

    assert out == dest.resolve()
    assert (dest / "_Good Strategy Bad Strategy.md").exists()
    assert (dest / "Chapters" / "01 - Chapter 1.md").exists()
    assert (dest / "Chapters" / "02 - Chapter 2.md").exists()
    assert (dest / "AI Working" / "chapter-notes-agent.md").exists()
    assert (dest / "AI Working" / "upload-checklist.md").exists()
    assert (dest / "AI Working" / "book-context.md").exists()
    assert (dest / "AI Working" / "vault-files.txt").exists()

    chapter = (dest / "Chapters" / "01 - Chapter 1.md").read_text(encoding="utf-8")
    assert "status: ai-draft-needed" in chapter
    assert 'author: "Richard Rumelt"' in chapter
    assert "[[_Good Strategy Bad Strategy]]" in chapter


def test_create_workspace_from_chapters_file_cli(tmp_path, capsys):
    module = load_module()
    base = tmp_path / "book.md"
    base.write_text("# Book\n", encoding="utf-8")
    chapters = tmp_path / "chapters.txt"
    chapters.write_text("Introduction\nThe Big Idea\n", encoding="utf-8")
    dest = tmp_path / "out"

    code = module.main([
        "create",
        "--base-note",
        str(base),
        "--dest",
        str(dest),
        "--title",
        "My Book",
        "--chapters-file",
        str(chapters),
    ])

    captured = capsys.readouterr()
    assert code == 0
    assert "Created Book Notes workspace" in captured.out
    assert (dest / "Chapters" / "01 - Introduction.md").exists()
    assert (dest / "Chapters" / "02 - The Big Idea.md").exists()
