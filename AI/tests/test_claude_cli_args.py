"""Claude CLI 어댑터의 호출 인자 — **한 줄이 없으면 자기 루프 층이 통째로 죽는다.**

실측(2026-07-29): `--tools ""` 없이 돌리면 `agent_loop` 의 프롬프트가 "쓸 수 있는 도구:" 로
도구 목록을 늘어놓는 순간 Claude 가 *자기* 내장 도구를 쓰려 들고, `--max-turns 1` 에 걸려
`stop_reason: tool_use` 로 실패한다. 3회 재시도 끝에 `interview_prep`·`coverletter_draft` 가
전부 결정론 폴백으로 나갔다 — 답변은 그럴듯해서 **겉으로는 정상처럼 보였다.**

이 테스트는 CLI 를 부르지 않는다(인자만 검사). 조용히 사라지는 종류의 결함이라 못을 박는다.
"""

from __future__ import annotations

from jobis_ai.claude_code_llm import ClaudeCodeChat, _COMMON_ARGS, extract_json


def test_builtin_tools_are_disabled():
    """`--tools ""` — 내장 도구를 끈다. 우리는 텍스트·JSON 생성만 필요하다."""

    assert "--tools" in _COMMON_ARGS
    assert _COMMON_ARGS[_COMMON_ARGS.index("--tools") + 1] == "", \
        '빈 문자열이어야 전부 꺼진다("default" 나 누락이면 켜진다)'


def test_single_turn_and_json_output():
    """한 번 답하고 끝 + JSON 봉투 — 도구를 끈 뒤에는 이 둘로 충분하다."""

    assert _COMMON_ARGS[_COMMON_ARGS.index("--max-turns") + 1] == "1"
    assert _COMMON_ARGS[_COMMON_ARGS.index("--output-format") + 1] == "json"
    assert "--strict-mcp-config" in _COMMON_ARGS, "전역 MCP 설정을 끌어오지 않는다"


def test_multi_word_cli_command_is_split():
    """`CLAUDE_CLI="wsl claude"` 처럼 다단 명령도 받는다."""

    assert ClaudeCodeChat(model="sonnet", cli="wsl claude").cli == ["wsl", "claude"]
    assert ClaudeCodeChat(model="sonnet", cli="").cli == ["claude"]


def test_json_extraction_strips_fences_and_prose():
    """CLI 는 코드펜스·앞뒤 잡담을 붙이는 일이 흔하다 — 벗겨서 파싱한다."""

    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('네, 결과입니다: {"a": 1} 이상입니다.') == '{"a": 1}'
    assert extract_json('{"a": 1}') == '{"a": 1}'
