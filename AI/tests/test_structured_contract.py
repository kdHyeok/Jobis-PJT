

# --- claude_code 공급자 — CLI 응답에서 JSON 본문 추출 (순수 함수) ------------
import pytest as _pytest

from jobis_ai.claude_code_llm import extract_json


# --- 조용한 폴백 금지 — 재시도 소진은 로그에 남는다 (07-29 사고) -------------
def test_retry_exhaustion_logs_a_warning(monkeypatch, caplog):
    """LLM 이 죽으면 **로그에 남아야 한다.** 경고 객체만으로는 아무도 안 읽는다.

    실측 사고: Claude CLI 인자 하나가 빠져 자기 루프 층이 통째로 죽었는데 결정론 폴백이
    그럴듯하게 답해서 몰랐다. 호출 지점 16개가 전부 run_structured 를 지나므로 여기서 못을 박는다.
    """

    import logging

    from pydantic import BaseModel

    from jobis_ai import structured

    class Dummy(BaseModel):
        value: str

    class DeadLLM:
        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages):
            raise RuntimeError("CLI 실패")

    monkeypatch.setattr(structured, "get_llm", lambda tier: DeadLLM())
    monkeypatch.setattr(structured, "_RETRY_BACKOFF_SEC", 0)   # 테스트가 4.5초 자지 않게
    with caplog.at_level(logging.WARNING, logger="jobis_ai.structured"):
        result, warnings = structured.run_structured(
            Dummy, "sys", "본문", node="test_node")

    assert result is None
    assert any(w["code"] == "llm_call_failed" for w in warnings)
    assert any(r.levelno == logging.WARNING and "test_node" in r.getMessage()
               for r in caplog.records), "재시도 소진이 로그에 안 남으면 실서버에서 안 보인다"


@_pytest.mark.parametrize("raw,expected", [
    ('```json\n{"a": 1}\n```', '{"a": 1}'),                    # 코드펜스
    ('```\n{"a": 1}\n```', '{"a": 1}'),                        # 언어 표기 없는 펜스
    ('물론이죠! {"a": 1} 입니다.', '{"a": 1}'),                # 앞뒤 잡담
    ('{"a": {"b": 2}}', '{"a": {"b": 2}}'),                    # 그대로
    ('JSON 없음', 'JSON 없음'),                                 # 못 찾으면 원문(파싱 실패는 호출부가)
])
def test_extract_json(raw, expected):
    assert extract_json(raw) == expected


# --- 형식 위반 재시도는 무엇이 틀렸는지 함께 보낸다 (08-03 사고) --------------
def test_format_violation_retry_carries_a_repair_hint(monkeypatch):
    """JSON 아닌 응답으로 실패하면 **다음 시도에 교정문이 실려야 한다.**

    실측 사고(2026-08-03): `posting_analysis` 자기 루프가 `LoopDecision` 을 JSON 대신
    마크다운(`**action**: read_posting …`)으로 받아 3회 재시도가 전부 같은 자리에서 죽고,
    결정론 폴백이 사용자에게 "분석 결과"처럼 나갔다. 같은 프롬프트 재전송은 형식 위반을
    고치지 못한다(stable-wrong). 네트워크 실패에는 붙이지 않는다 — 프롬프트 잘못이 아니다.
    """

    from pydantic import BaseModel, ValidationError

    from jobis_ai import structured

    class Dummy(BaseModel):
        value: str

    class MarkdownThenJson:
        """1회차는 실제 사고와 같은 마크다운, 2회차는 교정문을 받으면 제대로 낸다."""

        def __init__(self) -> None:
            self.seen: list[list[tuple[str, str]]] = []

        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages):
            self.seen.append(list(messages))
            if len(self.seen) == 1:
                # 실제로 받은 응답 형태를 그대로 재현한다.
                Dummy.model_validate_json("**value**: read_posting")
            return Dummy(value="ok")

    llm = MarkdownThenJson()
    monkeypatch.setattr(structured, "get_llm", lambda tier: llm)
    monkeypatch.setattr(structured, "_RETRY_BACKOFF_SEC", 0)
    result, warnings = structured.run_structured(Dummy, "sys", "본문", node="test_node")

    assert result is not None and result.value == "ok"
    # 1회차엔 교정문이 없고, 2회차엔 붙어 있다.
    assert len(llm.seen[0]) == 2
    hint = llm.seen[1][-1][1]
    assert "JSON 객체 하나만" in hint and "**필드**" in hint
    assert "validation error" in hint.lower()      # 무엇이 틀렸는지 그대로 돌려준다

    # 힌트는 쌓이지 않는다 — 재시도마다 base 위에 하나만.
    assert len(llm.seen[1]) == 3

    # 네트워크성 실패에는 붙이지 않는다.
    assert structured._repair_message(RuntimeError("Connection reset by peer")) is None
    assert structured._repair_message(ValidationError.from_exception_data(
        "Dummy", [])) is not None
