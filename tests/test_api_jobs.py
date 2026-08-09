"""Cockpit job routes: status, the honest "would do nothing" answer, and the force path.

No test starts a chain: equity_scout.jobs.start_job is monkeypatched, and the assertions
are about what the route decides, not about systemd.
"""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from equity_scout import jobs as jobs_mod
from equity_scout.api import create_app


@pytest.fixture
def client(tmp_path) -> TestClient:
    return TestClient(create_app(str(tmp_path / "equity_scout.db")))


@pytest.fixture
def started(monkeypatch) -> list[tuple[str, bool]]:
    """Records (job key, force) instead of launching anything.

    Also pins busy_lock to "free": without it these tests read the repo's real .state
    locks and would flip to 409 whenever a chain happens to be running on this machine.
    The one test that cares about the lock overrides it again.
    """
    calls: list[tuple[str, bool]] = []

    def fake_start(spec, root=jobs_mod.REPO_ROOT, *, force: bool) -> None:
        calls.append((spec.key, force))

    monkeypatch.setattr(jobs_mod, "start_job", fake_start)
    monkeypatch.setattr(jobs_mod, "busy_lock", lambda spec, root: None)
    return calls


def test_status_lists_both_jobs_with_their_labels(client) -> None:
    response = client.get("/api/jobs")
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert [job["key"] for job in jobs] == ["daily", "full"]
    assert jobs[0]["label"] == "Tages-Update"
    for job in jobs:
        assert set(job) >= {"running", "blocked", "progress", "tail"}


def test_unknown_job_is_a_404(client, started) -> None:
    response = client.post("/api/jobs/rm-rf/start", json={"force": False})
    assert response.status_code == 404
    assert started == []


def test_start_reports_the_blocked_reason_instead_of_starting(client, started, monkeypatch) -> None:
    monkeypatch.setattr(jobs_mod, "blocked_reason", lambda spec, root, *, today: "already_ran")
    response = client.post("/api/jobs/daily/start", json={"force": False})
    assert response.status_code == 200
    body = response.json()
    assert body["started"] is False
    assert body["reason"] == "already_ran"
    assert started == []  # nothing launched — the panel now offers "Trotzdem starten"


def test_force_starts_even_when_blocked(client, started, monkeypatch) -> None:
    monkeypatch.setattr(jobs_mod, "blocked_reason", lambda spec, root, *, today: "weekend")
    response = client.post("/api/jobs/daily/start", json={"force": True})
    assert response.status_code == 200
    assert response.json()["started"] is True
    assert response.json()["forced"] is True
    assert started == [("daily", True)]


def test_start_is_refused_while_a_lock_is_held(client, started, monkeypatch) -> None:
    # Overrides the fixture's "free" lock on purpose.
    monkeypatch.setattr(jobs_mod, "busy_lock", lambda spec, root: ".state/daily.lock")
    response = client.post("/api/jobs/daily/start", json={"force": True})
    assert response.status_code == 409
    assert started == []  # force never bypasses the lock — two chains, one database


def test_a_refused_launch_surfaces_as_a_500_with_the_reason(client, started, monkeypatch) -> None:
    def boom(spec, root=jobs_mod.REPO_ROOT, *, force: bool) -> None:
        raise subprocess.CalledProcessError(1, ["systemd-run"], stderr="Unit already exists.")

    monkeypatch.setattr(jobs_mod, "start_job", boom)
    monkeypatch.setattr(jobs_mod, "blocked_reason", lambda spec, root, *, today: None)
    response = client.post("/api/jobs/daily/start", json={"force": False})
    assert response.status_code == 500
    assert "Unit already exists." in response.json()["error"]
