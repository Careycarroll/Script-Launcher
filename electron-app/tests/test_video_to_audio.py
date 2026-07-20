from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "resources" / "python" / "scripts" / "video_to_audio.py"


def load_module():
    spec = importlib.util.spec_from_file_location("video_to_audio", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_help_exits_zero(capsys):
    module = load_module()
    with pytest.raises(SystemExit) as exc:
        module.build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    assert "video" in capsys.readouterr().out.lower()


def test_missing_video_fails_cleanly(capsys, tmp_path):
    module = load_module()
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")
    code = module.main([str(tmp_path / "missing.mp4"), "--ffmpeg", str(ffmpeg)])
    err = capsys.readouterr().err
    assert code == 1
    assert "Video not found" in err


def test_mp3_command_shape(tmp_path, monkeypatch, capsys):
    module = load_module()
    video = tmp_path / "clip.mov"
    video.write_bytes(b"fake")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")

    captured = {}

    def fake_run(cmd, capture_output=True, text=True):
        captured["cmd"] = list(cmd)
        Path(cmd[-1]).write_bytes(b"MP3")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.main([
        str(video),
        "--format",
        "mp3",
        "--bitrate",
        "192",
        "--ffmpeg",
        str(ffmpeg),
    ])
    out = capsys.readouterr().out

    assert code == 0
    assert str(tmp_path / "clip.mp3") in out
    assert (tmp_path / "clip.mp3").exists()
    assert "libmp3lame" in captured["cmd"]
    assert "192k" in captured["cmd"]
    assert "-vn" in captured["cmd"]


def test_wav_uses_pcm_and_ignores_bitrate(tmp_path, monkeypatch, capsys):
    module = load_module()
    video = tmp_path / "lecture.mkv"
    video.write_bytes(b"fake")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")

    captured = {}

    def fake_run(cmd, capture_output=True, text=True):
        captured["cmd"] = list(cmd)
        Path(cmd[-1]).write_bytes(b"WAV")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.main([str(video), "--format", "wav", "--ffmpeg", str(ffmpeg)])

    assert code == 0
    assert "pcm_s16le" in captured["cmd"]
    assert not any(arg == "-b:a" for arg in captured["cmd"])
    assert (tmp_path / "lecture.wav").exists()
    _ = capsys.readouterr()


def test_normalize_adds_loudnorm_filter(tmp_path, monkeypatch, capsys):
    module = load_module()
    video = tmp_path / "keynote.mp4"
    video.write_bytes(b"fake")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")

    captured = {}

    def fake_run(cmd, capture_output=True, text=True):
        captured["cmd"] = list(cmd)
        Path(cmd[-1]).write_bytes(b"OK")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.main([
        str(video),
        "--format",
        "m4a",
        "--normalize",
        "--ffmpeg",
        str(ffmpeg),
    ])
    _ = capsys.readouterr()

    assert code == 0
    assert "-af" in captured["cmd"]
    idx = captured["cmd"].index("-af")
    assert captured["cmd"][idx + 1].startswith("loudnorm=")


def test_out_dir_overrides_default(tmp_path, monkeypatch, capsys):
    module = load_module()
    video = tmp_path / "movie.mov"
    video.write_bytes(b"fake")
    out_dir = tmp_path / "out"
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_run(cmd, capture_output=True, text=True):
        Path(cmd[-1]).write_bytes(b"OK")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.main([
        str(video),
        "--format",
        "mp3",
        "--out-dir",
        str(out_dir),
        "--ffmpeg",
        str(ffmpeg),
    ])
    captured = capsys.readouterr()

    assert code == 0
    assert (out_dir / "movie.mp3").exists()
    assert str(out_dir / "movie.mp3") in captured.out
