from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "resources" / "python" / "scripts" / "text_to_audio.py"


def load_module():
    spec = importlib.util.spec_from_file_location("text_to_audio", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_help_exits_zero(capsys):
    module = load_module()
    with pytest.raises(SystemExit) as exc:
        module.build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    assert "text" in capsys.readouterr().out.lower()


def test_missing_text_fails_cleanly(capsys, tmp_path):
    module = load_module()
    code = module.main([str(tmp_path / "missing.txt")])
    assert code == 1
    assert "Text file not found" in capsys.readouterr().err


def test_wav_flow_calls_piper(tmp_path, monkeypatch, capsys):
    module = load_module()
    text = tmp_path / "note.txt"
    text.write_text("hello", encoding="utf-8")

    def fake_run(cmd, capture_output=True, text=True):
        joined = " ".join(cmd)
        assert "tts_piper.py" in joined
        wav_path = Path(cmd[cmd.index("--out-dir") + 1]) / cmd[cmd.index("--out") + 1]
        wav_path.write_bytes(b"RIFF")
        return subprocess.CompletedProcess(cmd, 0, stdout=f"Done: {wav_path}\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.main([str(text), "--voice", "Ryan"])
    out = capsys.readouterr().out
    assert code == 0
    assert str(tmp_path / "note.wav") in out
    assert (tmp_path / "note.wav").exists()


def test_mp3_flow_transcodes_and_drops_wav(tmp_path, monkeypatch, capsys):
    module = load_module()
    text = tmp_path / "lecture.txt"
    text.write_text("hello", encoding="utf-8")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")

    calls = []

    def fake_run(cmd, capture_output=True, text=True):
        calls.append(cmd)
        joined = " ".join(cmd)
        if "tts_piper.py" in joined:
            wav_path = Path(cmd[cmd.index("--out-dir") + 1]) / cmd[cmd.index("--out") + 1]
            wav_path.write_bytes(b"RIFF")
            return subprocess.CompletedProcess(cmd, 0, stdout=f"Done: {wav_path}\n", stderr="")
        if cmd[0] == str(ffmpeg):
            Path(cmd[-1]).write_bytes(b"MP3")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.main([str(text), "--format", "mp3", "--bitrate", "128", "--ffmpeg", str(ffmpeg)])
    out = capsys.readouterr().out
    assert code == 0
    assert str(tmp_path / "lecture.mp3") in out
    assert (tmp_path / "lecture.mp3").exists()
    assert not (tmp_path / "lecture.wav").exists()
    assert any(c and c[0] == str(ffmpeg) and "libmp3lame" in c and "128k" in c for c in calls)


def test_keep_wav_preserves_intermediate(tmp_path, monkeypatch):
    module = load_module()
    text = tmp_path / "keep.txt"
    text.write_text("hello", encoding="utf-8")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_run(cmd, capture_output=True, text=True):
        joined = " ".join(cmd)
        if "tts_piper.py" in joined:
            wav_path = Path(cmd[cmd.index("--out-dir") + 1]) / cmd[cmd.index("--out") + 1]
            wav_path.write_bytes(b"RIFF")
            return subprocess.CompletedProcess(cmd, 0, stdout=f"Done: {wav_path}\n", stderr="")
        if cmd[0] == str(ffmpeg):
            Path(cmd[-1]).write_bytes(b"M4A")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.main([str(text), "--format", "m4a", "--keep-wav", "--ffmpeg", str(ffmpeg)])
    assert code == 0
    assert (tmp_path / "keep.m4a").exists()
    assert (tmp_path / "keep.wav").exists()
