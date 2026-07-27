

# --- claude_code 공급자 — CLI 응답에서 JSON 본문 추출 (순수 함수) ------------
import pytest as _pytest

from jobis_ai.claude_code_llm import extract_json


@_pytest.mark.parametrize("raw,expected", [
    ('```json\n{"a": 1}\n```', '{"a": 1}'),                    # 코드펜스
    ('```\n{"a": 1}\n```', '{"a": 1}'),                        # 언어 표기 없는 펜스
    ('물론이죠! {"a": 1} 입니다.', '{"a": 1}'),                # 앞뒤 잡담
    ('{"a": {"b": 2}}', '{"a": {"b": 2}}'),                    # 그대로
    ('JSON 없음', 'JSON 없음'),                                 # 못 찾으면 원문(파싱 실패는 호출부가)
])
def test_extract_json(raw, expected):
    assert extract_json(raw) == expected
