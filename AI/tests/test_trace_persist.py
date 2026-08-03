# -*- coding: utf-8 -*-
"""trace 파일 영속화(D127) — 프로토타입 2.0.0 의 런별 trace 이식."""

import json

from jobis_ai import trace


def test_recording_persists_events_to_file(tmp_path, monkeypatch):
    """JOBIS_TRACE_DIR 이 설정되면 턴 하나의 이벤트가 JSON 파일 하나로 남는다."""
    monkeypatch.setenv("JOBIS_TRACE_DIR", str(tmp_path))
    with trace.recording():
        trace.emit("planner", "계획", {"agents": ["fit_analysis"]})
        trace.emit("agent_end", "fit_analysis", {"ok": True})

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert [e["kind"] for e in saved["events"]] == ["planner", "agent_end"]
    assert saved["events"][0]["detail"] == {"agents": ["fit_analysis"]}


def test_nested_recording_writes_once(tmp_path, monkeypatch):
    """중첩 레코더는 부모가 이벤트를 다 받는다 — 파일은 최상위 한 번만 쓴다."""
    monkeypatch.setenv("JOBIS_TRACE_DIR", str(tmp_path))
    with trace.recording():
        with trace.recording():
            trace.emit("node", "parse", {})

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert [e["kind"] for e in saved["events"]] == ["node"]


def test_no_env_no_file_and_empty_recording_no_file(tmp_path, monkeypatch):
    """opt-in 이다 — 환경변수가 없으면 안 쓰고, 이벤트 0건이면 빈 파일을 만들지 않는다."""
    monkeypatch.delenv("JOBIS_TRACE_DIR", raising=False)
    with trace.recording():
        trace.emit("node", "parse", {})
    monkeypatch.setenv("JOBIS_TRACE_DIR", str(tmp_path))
    with trace.recording():
        pass
    assert list(tmp_path.glob("*.json")) == []
