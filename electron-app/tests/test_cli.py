"""CLI shape — argument parsing, --list, --introspect, --echo, --help."""
import json
import pytest


def test_help_exits_zero(docpipe):
    r = docpipe("--help")
    assert r.returncode == 0
    assert "usage" in r.stdout.lower() or "usage" in r.stderr.lower()


def test_list_includes_all_operations(docpipe):
    r = docpipe("--list")
    assert r.returncode == 0
    expected = [
        "pdf_to_txt", "images_to_pdf", "pptx_to_pdf",
        "pdf_merge", "pdf_strip", "pdf_bookmark_analyze",
        "pdf_bookmark_add", "pdf_split",
    ]
    for op in expected:
        assert op in r.stdout, f"missing {op} in --list output"


def test_list_includes_pipeline(docpipe):
    r = docpipe("--list")
    assert "pptx_to_txt" in r.stdout


def test_introspect_returns_valid_json(docpipe):
    r = docpipe("--introspect")
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert isinstance(data, dict)
    assert "operations" in data
    assert "pipelines" in data


def test_introspect_operations_have_required_fields(docpipe):
    r = docpipe("--introspect")
    data = json.loads(r.stdout)
    required = {"name", "src", "dst", "input_arity", "output_arity"}
    for op in data["operations"]:
        missing = required - set(op.keys())
        assert not missing, f"{op.get('name', '?')} missing fields: {missing}"


def test_echo_returns_argv(docpipe):
    r = docpipe("--echo", "pdf_to_txt", "input.pdf", "--pdf_to_txt-layout", "plain")
    assert r.returncode == 0
    data = json.loads(r.stdout)
    argv = data["received_argv"]
    assert "pdf_to_txt" in argv
    assert "input.pdf" in argv
    assert "--pdf_to_txt-layout" in argv
    assert "plain" in argv


def test_unknown_operation_fails(docpipe):
    r = docpipe("nonexistent_op", "input.pdf")
    assert r.returncode != 0
