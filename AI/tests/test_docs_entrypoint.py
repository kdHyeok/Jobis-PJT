"""자동 로드 문서의 무결성 — **지도가 썩으면 문서가 없는 것과 같다.**

`CLAUDE.md` 는 Claude Code 가 자동으로 읽는 진입점이고, `@경로` 로 규약(`AGENTS.md`)과 지금
상태(`작업로그/지금상태.md`)를 임포트한다. 임포트 경로나 지도의 링크가 깨지면 **조용히** 규약이
사라진다 — 이 저장소가 문서 드리프트로 세 번 대가를 치른 뒤 넣은 방어다(비교 문서 §2-5).

여기서 내용을 검사하지는 않는다(그건 사람이 읽는다). **경로가 살아 있는지와 자동 로드가
비대해지지 않는지**만 본다.
"""

from __future__ import annotations

import re
from pathlib import Path

_AI = Path(__file__).resolve().parents[1]
_CLAUDE = _AI / "CLAUDE.md"

# 자동 로드는 매 세션 비용이다. 넘으면 상세 문서로 밀어낸다.
_MAX_AUTOLOADED_LINES = 130
_MAX_STATE_LINES = 25


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports() -> list[str]:
    """`@경로` 임포트 목록 (줄 맨 앞의 @ 만 — 본문 중의 이메일·데코레이터와 구분)."""

    return re.findall(r"^@(\S+)\s*$", _text(_CLAUDE), re.MULTILINE)


def test_entrypoint_imports_the_conventions_and_the_state():
    """규약과 지금 상태 둘 다 자동 로드된다 — 하나라도 빠지면 §2-5 문제가 되돌아온다."""

    imported = _imports()
    assert "AGENTS.md" in imported, "코딩 규약이 자동 로드되지 않는다"
    assert any("지금상태" in p for p in imported), "지금 상태가 자동 로드되지 않는다"


def test_every_import_target_exists():
    """임포트 경로가 깨지면 규약이 조용히 사라진다."""

    for target in _imports():
        assert (_AI / target).is_file(), f"임포트 대상이 없다: {target}"


def test_autoloaded_docs_stay_small():
    """자동 로드 총량 상한 — 커지면 매 세션 비용이고, 커지는 문서는 낡는다."""

    total = sum(len(_text(_AI / t).splitlines()) for t in _imports())
    assert total <= _MAX_AUTOLOADED_LINES, (
        f"자동 로드가 {total}줄이다(상한 {_MAX_AUTOLOADED_LINES}). "
        "수치·구조는 explain 이 답하므로 상세 문서로 밀어낼 것")

    state = next(_AI / t for t in _imports() if "지금상태" in t)
    assert len(_text(state).splitlines()) <= _MAX_STATE_LINES, \
        "지금상태.md 는 '지금 어디인가'만 — 상세는 다음작업.md 로"


def test_document_map_has_no_dead_links():
    """지도가 가리키는 파일이 실제로 있어야 한다 — 죽은 링크는 지도가 없는 것보다 나쁘다."""

    # 표의 백틱 경로 중 이 디렉터리 기준 상대 경로만 검사(루트 CLAUDE.md 등 서술은 제외).
    candidates = re.findall(r"`([\w가-힣/\-\.]+\.(?:md|json))`", _text(_CLAUDE))
    checked = 0
    for path in candidates:
        target = _AI / path
        if path == "CLAUDE.md":          # 루트 CLAUDE.md 를 가리키는 서술
            continue
        assert target.exists(), f"지도의 죽은 링크: {path}"
        checked += 1
    assert checked >= 8, "지도가 비어 있다(경로 표기가 바뀌었는지 확인)"


def test_conventions_point_at_code_not_numbers():
    """`AGENTS.md` 는 **낡지 않는 것만** 담는다 — 물어보는 법(explain·pytest)이 있어야 한다."""

    agents = _text(_AI / "AGENTS.md")
    assert "jobis_ai.explain" in agents, "구조를 코드에 물어보는 법이 없다"
    assert "pytest -q" in agents
    # 계층·금지형·수정 순서가 빠지면 규약이 아니다.
    for anchor in ("모른다", "금지는", "도구는 말하지 않는다", "어휘"):
        assert anchor in agents, f"규약에 '{anchor}' 항목이 없다"


def test_decision_log_threads_reversed_decisions():
    """결정 로그의 유일한 계약: **뒤집힌 결정을 지우지 않고 잇는다.**

    지우면 왜 그 길을 안 갔는지가 사라지고 다음 사람이 같은 실수를 반복한다 — 이 세션만 해도
    프롬프트 규칙을 넣고 되돌린 이력이 평가 기록 안에 묻혀 있었다(D41 → D44).
    """

    log = _text(_AI / "docs" / "decisions.md")

    ids = re.findall(r"^### (D\d+) ", log, re.MULTILINE)
    assert len(ids) >= 20, "결정 로그가 비어 있다"
    assert ids == sorted(ids, key=lambda d: int(d[1:])), "D 번호가 시간순이 아니다"
    assert len(set(ids)) == len(ids), f"D 번호 중복: {[d for d in ids if ids.count(d) > 1]}"

    # 뒤집힘 표시가 가리키는 번호가 실존해야 한다 — 죽은 실은 잇지 않은 것과 같다.
    linked = re.findall(r"이후 (?:변경|대체) \((D\d+)(?:,\s*(D\d+))?\)", log)
    referenced = {d for pair in linked for d in pair if d}
    assert referenced, "뒤집힌 결정이 하나도 표시돼 있지 않다"
    assert referenced <= set(ids), f"존재하지 않는 결정을 가리킨다: {referenced - set(ids)}"


def test_entrypoint_points_at_the_decision_log():
    """지도와 규약이 결정 로그를 가리켜야 찾을 수 있다."""

    assert "decisions.md" in _text(_CLAUDE)
    assert "decisions.md" in _text(_AI / "AGENTS.md")
