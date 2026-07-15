from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "resources" / "python" / "scripts" / "pdf_to_audio.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pdf_to_audio", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_help_exits_zero(capsys):
    module = load_module()
    with pytest.raises(SystemExit) as exc:
        module.build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    assert "PDF" in capsys.readouterr().out


def test_invalid_pdf_path_fails_cleanly(capsys):
    module = load_module()
    code = module.main(["/no/such/input.pdf"])
    captured = capsys.readouterr()
    assert code == 1
    assert "PDF not found" in captured.err


def test_parse_output_path_strips_status_prefix(tmp_path):
    module = load_module()
    wav = tmp_path / "sample.wav"
    wav.write_bytes(b"RIFF")

    parsed = module.parse_first_output_path(f"Done: {wav}\n", tmp_path / "fallback.wav")

    assert parsed == wav


def test_wav_path_naming_and_subprocess_calls(tmp_path, monkeypatch, capsys):
    module = load_module()
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    out_dir = tmp_path / "out"

    calls = []

    def fake_run(cmd, capture_output=True, text=True):
        calls.append(cmd)
        joined = " ".join(cmd)
        if "docpipe.py" in joined:
            text_path = Path(cmd[cmd.index("--out") + 1])
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text("hello", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout=str(text_path) + "\n", stderr="")
        if "tts_piper.py" in joined:
            wav_path = Path(cmd[cmd.index("--out-dir") + 1]) / cmd[cmd.index("--out") + 1]
            wav_path.write_bytes(b"RIFF")
            return subprocess.CompletedProcess(cmd, 0, stdout=f"Done: {wav_path}\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.main([str(pdf), "--out-dir", str(out_dir), "--voice", "Ryan"])
    captured = capsys.readouterr()

    assert code == 0
    assert str(out_dir / "sample.wav") in captured.out
    assert (out_dir / "sample.txt").exists()
    assert (out_dir / "sample.wav").exists()
    assert any("docpipe.py" in " ".join(c) for c in calls)
    assert any("tts_piper.py" in " ".join(c) for c in calls)


def test_mp3_format_calls_ffmpeg_and_removes_intermediate_wav(tmp_path, monkeypatch, capsys):
    module = load_module()
    pdf = tmp_path / "lecture.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")

    calls = []

    def fake_run(cmd, capture_output=True, text=True):
        calls.append(cmd)
        joined = " ".join(cmd)
        if "docpipe.py" in joined:
            text_path = Path(cmd[cmd.index("--out") + 1])
            text_path.write_text("hello", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout=str(text_path) + "\n", stderr="")
        if "tts_piper.py" in joined:
            wav_path = Path(cmd[cmd.index("--out-dir") + 1]) / cmd[cmd.index("--out") + 1]
            wav_path.write_bytes(b"RIFF")
            return subprocess.CompletedProcess(cmd, 0, stdout=f"Done: {wav_path}\n", stderr="")
        if cmd[0] == str(ffmpeg):
            Path(cmd[-1]).write_bytes(b"MP3")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.main([str(pdf), "--format", "mp3", "--ffmpeg", str(ffmpeg)])
    captured = capsys.readouterr()

    assert code == 0
    assert str(tmp_path / "lecture.mp3") in captured.out
    assert (tmp_path / "lecture.mp3").exists()
    assert not (tmp_path / "lecture.wav").exists()
    assert any(c and c[0] == str(ffmpeg) and "libmp3lame" in c for c in calls)


def test_discard_text_removes_intermediate_text(tmp_path, monkeypatch):
    module = load_module()
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")

    def fake_run(cmd, capture_output=True, text=True):
        joined = " ".join(cmd)
        if "docpipe.py" in joined:
            text_path = Path(cmd[cmd.index("--out") + 1])
            text_path.write_text("hello", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout=str(text_path) + "\n", stderr="")
        if "tts_piper.py" in joined:
            wav_path = Path(cmd[cmd.index("--out-dir") + 1]) / cmd[cmd.index("--out") + 1]
            wav_path.write_bytes(b"RIFF")
            return subprocess.CompletedProcess(cmd, 0, stdout=f"Done: {wav_path}\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.main([str(pdf), "--discard-text"])

    assert code == 0
    assert not (tmp_path / "paper.txt").exists()
    assert (tmp_path / "paper.wav").exists()
