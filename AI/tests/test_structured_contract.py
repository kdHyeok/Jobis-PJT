

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
