import subprocess

import equity_scout.analysis as analysis_mod
from equity_scout.analysis import THESIS_UNAVAILABLE_PREFIX, ClaudeCliAnalysis, FakeAnalysis, attach_theses
from equity_scout.models import Instrument, Pick


def _pick(t):
    inst = Instrument(t, t, "E", "US", "USD", "Tech")
    return Pick(inst, "aggressive", 1, 0.8,
                {"value": 0.1, "quality": 0.1, "momentum": 0.9, "growth": 0.9})


def test_attach_theses_fills_thesis_for_each_pick():
    buckets = {"aggressive": [_pick("AGG")]}
    out = attach_theses(buckets, FakeAnalysis())
    thesis = out["aggressive"][0].thesis
    assert thesis is not None and "AGG" in thesis


def test_attach_theses_is_noop_when_provider_none():
    buckets = {"aggressive": [_pick("AGG")]}
    out = attach_theses(buckets, None)
    assert out["aggressive"][0].thesis is None


def test_attach_theses_respects_max_per_bucket():
    inst = Instrument("X", "X", "E", "US", "USD", "Tech")
    picks = [Pick(inst, "aggressive", rank, 0.8,
                  {"value": 0.1, "quality": 0.1, "momentum": 0.9, "growth": 0.9})
             for rank in (1, 2, 3)]
    out = attach_theses({"aggressive": picks}, FakeAnalysis(), max_per_bucket=2)
    theses = [p.thesis for p in out["aggressive"]]
    assert theses[0] is not None and theses[1] is not None  # ranks 1,2 analyzed
    assert theses[2] is None  # rank 3 skipped (cost cap)


# --- ClaudeCliAnalysis: contract-tests the subprocess boundary via a mocked subprocess.run ---


def test_claude_cli_returns_stdout_on_success(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="Solide Story.\n", stderr="")

    monkeypatch.setattr(analysis_mod.subprocess, "run", fake_run)
    assert ClaudeCliAnalysis().thesis_for(_pick("AGG")) == "Solide Story."


def test_claude_cli_nonzero_exit_is_unavailable_even_with_stdout(monkeypatch):
    # A CLI that prints an error to stdout and still exits non-zero must not have that text
    # silently adopted as the thesis — this is the exact bug being hardened against.
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, returncode=1, stdout="permission denied", stderr="auth error"
        )

    monkeypatch.setattr(analysis_mod.subprocess, "run", fake_run)
    thesis = ClaudeCliAnalysis().thesis_for(_pick("AGG"))
    assert thesis.startswith(THESIS_UNAVAILABLE_PREFIX)
    assert "auth error" in thesis
    assert "permission denied" not in thesis


def test_claude_cli_nonzero_exit_falls_back_to_exit_code_when_no_stderr(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=2, stdout="", stderr="")

    monkeypatch.setattr(analysis_mod.subprocess, "run", fake_run)
    thesis = ClaudeCliAnalysis().thesis_for(_pick("AGG"))
    assert thesis.startswith(THESIS_UNAVAILABLE_PREFIX)
    assert "exit code 2" in thesis


def test_claude_cli_timeout_is_unavailable(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    monkeypatch.setattr(analysis_mod.subprocess, "run", fake_run)
    thesis = ClaudeCliAnalysis(timeout_s=5).thesis_for(_pick("AGG"))
    assert thesis.startswith(THESIS_UNAVAILABLE_PREFIX)
    assert "Timeout" in thesis


def test_claude_cli_missing_binary_is_unavailable(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(analysis_mod.subprocess, "run", fake_run)
    thesis = ClaudeCliAnalysis().thesis_for(_pick("AGG"))
    assert thesis.startswith(THESIS_UNAVAILABLE_PREFIX)


def test_claude_cli_empty_stdout_is_unavailable(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="   \n", stderr="")

    monkeypatch.setattr(analysis_mod.subprocess, "run", fake_run)
    thesis = ClaudeCliAnalysis().thesis_for(_pick("AGG"))
    assert thesis.startswith(THESIS_UNAVAILABLE_PREFIX)
    assert "leere Antwort" in thesis
