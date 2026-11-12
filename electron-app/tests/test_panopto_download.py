from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

pytest.importorskip("yt_dlp")

SCRIPT = Path(__file__).resolve().parents[1] / "resources" / "python" / "scripts" / "panopto_download.py"


def load_module():
    spec = importlib.util.spec_from_file_location("panopto_download", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parser_external_srt_default_true():
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args([
        "https://unc.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=123",
        "--out-dir", "/tmp",
        "--prefix", "01",
    ])
    assert args.external_srt is True
    assert args.captions is True
    assert args.embed_subs is True


def test_parser_no_external_srt_flag():
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args([
        "https://unc.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=123",
        "--out-dir", "/tmp",
        "--prefix", "01",
        "--no-external-srt",
    ])
    assert args.external_srt is False


def test_parser_srt_alias_flags():
    module = load_module()
    parser = module.build_parser()
    args_no = parser.parse_args([
        "https://unc.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=123",
        "--out-dir", "/tmp",
        "--prefix", "01",
        "--no-srt",
    ])
    assert args_no.external_srt is False

    args_yes = parser.parse_args([
        "https://unc.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=123",
        "--out-dir", "/tmp",
        "--prefix", "01",
        "--srt",
    ])
    assert args_yes.external_srt is True


def test_build_ydl_opts_defaults_embed_and_external_srt(tmp_path):
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args([
        "https://unc.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=123",
        "--out-dir", str(tmp_path),
        "--prefix", "01",
    ])
    opts = module.build_ydl_opts(args, tmp_path, "01")
    assert opts.get("writesubtitles") is True
    assert opts.get("embedsubtitles") is True
    assert opts.get("merge_output_format") == "mp4"

    pps = opts.get("postprocessors", [])
    assert len(pps) == 2
    assert pps[0] == {"key": "FFmpegSubtitlesConvertor", "format": "srt"}
    assert pps[1] == {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": True}


def test_build_ydl_opts_embed_without_external_srt(tmp_path):
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args([
        "https://unc.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=123",
        "--out-dir", str(tmp_path),
        "--prefix", "01",
        "--no-external-srt",
    ])
    opts = module.build_ydl_opts(args, tmp_path, "01")
    assert opts.get("writesubtitles") is True
    assert opts.get("embedsubtitles") is True

    pps = opts.get("postprocessors", [])
    assert len(pps) == 1
    assert pps[0] == {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False}


def test_build_ydl_opts_external_srt_without_embed(tmp_path):
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args([
        "https://unc.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=123",
        "--out-dir", str(tmp_path),
        "--prefix", "01",
        "--no-embed-subs",
    ])
    opts = module.build_ydl_opts(args, tmp_path, "01")
    assert opts.get("writesubtitles") is True
    assert "embedsubtitles" not in opts

    pps = opts.get("postprocessors", [])
    assert len(pps) == 1
    assert pps[0] == {"key": "FFmpegSubtitlesConvertor", "format": "srt"}


def test_build_ydl_opts_sidecar_vtt_only(tmp_path):
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args([
        "https://unc.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=123",
        "--out-dir", str(tmp_path),
        "--prefix", "01",
        "--no-embed-subs",
        "--no-external-srt",
    ])
    opts = module.build_ydl_opts(args, tmp_path, "01")
    assert opts.get("writesubtitles") is True
    assert "embedsubtitles" not in opts
    assert "postprocessors" not in opts
    assert opts.get("subtitlesformat") == "vtt"


def test_build_ydl_opts_no_captions(tmp_path):
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args([
        "https://unc.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=123",
        "--out-dir", str(tmp_path),
        "--prefix", "01",
        "--no-captions",
    ])
    opts = module.build_ydl_opts(args, tmp_path, "01")
    assert "writesubtitles" not in opts
    assert "postprocessors" not in opts


def test_normalize_external_srt_renames_en_tag(tmp_path):
    module = load_module()
    # Setup test files
    video = tmp_path / "01. Introduction to Bio.mp4"
    video.write_bytes(b"dummy video")
    sub_en = tmp_path / "01. Introduction to Bio.en.srt"
    sub_en.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")

    # Another prefix should not be touched
    sub_other = tmp_path / "02. Chemistry.en.srt"
    sub_other.write_text("dummy")

    renamed = module.normalize_external_srt(tmp_path, "01")
    target = tmp_path / "01. Introduction to Bio.srt"

    assert target.exists()
    assert not sub_en.exists()
    assert sub_other.exists()
    assert target in renamed
    assert target.read_text().startswith("1\n00:00:00,000")


def test_find_final_video_path_prefers_video_over_srt(tmp_path):
    module = load_module()
    video = tmp_path / "01. Lecture.mp4"
    video.write_bytes(b"video")
    sub = tmp_path / "01. Lecture.srt"
    sub.write_text("subtitles")

    found = module.find_final_video_path(tmp_path, "01")
    assert found == video
