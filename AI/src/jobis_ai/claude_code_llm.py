"""Claude Code CLI 어댑터 — 이 머신에 로그인된 Claude 구독(팀 플랜)으로 LLM 을 호출한다.

GMS 키 없이(=토큰 비용 없이) 개발 반복을 돌리기 위한 공급자 옵션이다. Anthropic API 키가
아니라 **Claude Code CLI 의 로그인 세션**을 쓴다 — `claude -p`(headless) 가 구독 시트로
호출하고, 우리는 그 출력을 구조화 스키마로 검증한다.

get_llm() 이 돌려주는 다른 공급자(LangChain Chat 모델)와 같은 표면만 노출한다:
`.with_structured_output(schema)` → `.invoke(messages)`. run_structured 의 재시도·트레이스
루프가 그대로 적용되도록, 실패는 조용히 삼키지 않고 예외로 올린다.

한계(정직하게):
- 서버 배포용이 아니다 — CLI 로그인 세션이 있는 개발 머신에서만 동작한다.
- 호출당 CLI 기동 오버헤드(수 초)가 있다. GMS(gpt-4.1-mini)보다 느리다.
- 구조화 출력이 서버 강제형이 아니라 지시+검증형이다. 검증 실패는 예외 → 재시도.
- **내장 도구를 끈다**(`--tools ""`). 우리 프롬프트에 "도구" 목록이 나오면 Claude 가 자기
  도구를 쓰려 들어 `--max-turns 1` 에 걸린다 — 아래 `_COMMON_ARGS` 주석 참고.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import tempfile
from typing import Any

# 프롬프트가 요구한 JSON 을 코드펜스로 감싸 돌려주는 일이 흔하다 — 벗겨서 파싱한다.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# 호출당 상한(초). CLI 기동 + 모델 응답. 판정 파이프라인 한 노드가 이보다 오래 걸리면 실패가 맞다.
_CALL_TIMEOUT_SEC = 180

# 모든 호출에 붙는 인자.
#
# `--tools ""` — **내장 도구(Read/Bash/Edit…)를 전부 끈다.** 없으면 우리 프롬프트가 "쓸 수 있는
# 도구:" 라고 도구 목록을 늘어놓는 순간(agents/agent_loop 의 자기 루프) Claude 가 *자기* 도구를
# 쓰려 들고, `--max-turns 1` 에 걸려 `stop_reason: tool_use` 로 실패한다. 실측(2026-07-29):
# `interview_prep`·`coverletter_draft` 루프가 3회 재시도 끝에 전부 죽어 결정론 폴백으로
# 나갔다 — 자기 루프 층이 이 공급자에서 통째로 꺼져 있었다.
# 우리가 원하는 것은 텍스트·JSON 생성 하나뿐이므로 도구를 줄 이유가 없다.
#
# `--strict-mcp-config` — 전역 설정의 MCP 서버를 로드하지 않는다(기동이 수 초 빨라진다).
# `--max-turns 1` — 한 번 답하고 끝. 도구를 끈 뒤에는 이걸로 충분하다.
_COMMON_ARGS = ["--output-format", "json", "--max-turns", "1",
                "--strict-mcp-config", "--tools", ""]

_ERROR_DETAIL_LIMIT = 1000


class ClaudeCodeCLIError(RuntimeError):
    """Claude CLI 호출 실패.

    ``retryable`` 은 호출부가 같은 요청을 다시 보낼 가치가 있는지 나타낸다. 주간 사용 한도처럼
    재실행해도 결과가 바뀌지 않는 오류는 False 로 올려 불필요한 CLI 재기동을 막는다.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _compact_error_detail(value: Any) -> str:
    """로그 한 줄에 안전하게 넣을 수 있도록 오류 설명만 짧게 정리한다."""

    text = " ".join(str(value or "").split())
    return text[:_ERROR_DETAIL_LIMIT]


def _decode_wrapper(stdout: str) -> dict[str, Any] | None:
    """Claude CLI JSON wrapper 를 읽는다. 비 JSON stderr 경로는 호출부가 별도로 처리한다."""

    try:
        parsed = json.loads(stdout or "")
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _raise_cli_error(out: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """종료 코드와 JSON wrapper 를 함께 판정해 사람이 읽을 수 있는 예외로 바꾼다.

    Claude CLI 는 API 오류도 stdout 의 JSON ``result`` 에 싣는다. 기존 구현은 stdout 앞
    300자만 남겨 뒤쪽의 실제 원인(예: 주간 한도와 리셋 시각)을 잘라 버렸다.
    """

    wrapper = _decode_wrapper(out.stdout)
    is_error = out.returncode != 0 or bool(wrapper and wrapper.get("is_error"))
    if not is_error:
        if wrapper is None:
            detail = _compact_error_detail(out.stderr or out.stdout) or "빈 응답"
            raise ClaudeCodeCLIError(f"claude CLI JSON 응답 파싱 실패: {detail}")
        return wrapper

    status = wrapper.get("api_error_status") if wrapper else None
    terminal_reason = wrapper.get("terminal_reason") if wrapper else None
    detail = _compact_error_detail(
        (wrapper.get("result") if wrapper else None) or out.stderr or out.stdout
    ) or "상세 오류 없음"

    # 일반 429는 잠깐 뒤 회복할 수 있지만, 구독 주간 한도는 리셋 전까지 같은 결과라 재시도가
    # 무의미하다. 문구와 상태를 함께 보아 이 경우만 영구 실패로 분류한다.
    weekly_limit = status == 429 and (
        "weekly limit" in detail.lower() or "resets" in detail.lower()
    )
    if weekly_limit:
        raise ClaudeCodeCLIError(
            f"claude CLI 사용 한도 초과 (HTTP 429): {detail}", retryable=False
        )

    context = []
    if status is not None:
        context.append(f"HTTP {status}")
    if terminal_reason:
        context.append(str(terminal_reason))
    context_text = f" ({', '.join(context)})" if context else ""
    raise ClaudeCodeCLIError(
        f"claude CLI 종료 코드 {out.returncode}{context_text}: {detail}"
    )


def _run_cli(cli: list[str], model: str, prompt: str) -> dict[str, Any]:
    """Claude CLI 한 번을 실행하고 성공 wrapper 만 반환한다."""

    try:
        out = subprocess.run(
            [*cli, "-p", prompt, "--model", model, *_COMMON_ARGS],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_CALL_TIMEOUT_SEC, stdin=subprocess.DEVNULL,
            # 레포 밖에서 실행 — 프로젝트 CLAUDE.md·설정·훅이 판정 프롬프트에 섞이지 않게.
            cwd=tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired 문자열에는 전체 명령(즉 프롬프트 원문)이 포함된다. 사용자 입력을 로그에
        # 유출하지 않고 제한시간만 알린다.
        raise ClaudeCodeCLIError(
            f"claude CLI 응답 시간 초과 ({_CALL_TIMEOUT_SEC}초)"
        ) from exc
    except OSError as exc:
        raise ClaudeCodeCLIError(
            f"claude CLI 실행 실패: {_compact_error_detail(exc)}", retryable=False
        ) from exc
    return _raise_cli_error(out)


def extract_json(text: str) -> str:
    """CLI 응답 텍스트에서 JSON 본문을 꺼낸다. 코드펜스·앞뒤 잡담을 벗긴다.

    못 찾으면 원문을 그대로 돌려준다 — 파싱 실패는 호출부(model_validate_json)가
    예외로 올려 재시도로 이어진다.
    """

    text = (text or "").strip()
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1).strip()
    # 펜스 없이 앞뒤에 말이 붙은 경우 — 첫 { 부터 마지막 } 까지.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return text


class ClaudeCodeChat:
    """`claude -p` 를 부르는 최소 어댑터. get_llm() 계약(with_structured_output)만 구현."""

    def __init__(self, model: str, cli: str = "claude") -> None:
        self.model = model
        # "wsl claude" 같은 다단 명령도 허용 — 환경변수 CLAUDE_CLI 로 재지정한다.
        self.cli = shlex.split(cli or "claude")

    def with_structured_output(self, schema: type, **_ignored: Any) -> "_Structured":
        return _Structured(self, schema)

    def invoke(self, messages: list[tuple[str, str]]) -> "_TextResult":
        """구조화 없는 텍스트 생성 — run_streaming_text(표현 계층)의 비스트리밍 폴백 경로.

        CLI 는 토큰 스트리밍을 지원하지 않으므로 완성본을 한 번에 돌려준다. 검증 계층은
        호출부가 완성본에 대해 수행한다(금지표현 사후 검증 — career_chat 등).
        """

        system = "\n\n".join(m[1] for m in messages if m[0] == "system")
        human = "\n\n".join(m[1] for m in messages if m[0] != "system")
        prompt = f"{system}\n\n---\n[입력]\n{human}"

        wrapper = _run_cli(self.cli, self.model, prompt)
        return _TextResult(str(wrapper.get("result") or ""))


class _TextResult:
    """invoke() 반환 — LangChain 메시지의 .content 계약만 흉내낸다."""

    def __init__(self, content: str) -> None:
        self.content = content


class _Structured:
    def __init__(self, chat: ClaudeCodeChat, schema: type) -> None:
        self._chat = chat
        self._schema = schema

    def invoke(self, messages: list[tuple[str, str]]) -> Any:
        """(system, human) 메시지 → schema 인스턴스. 실패는 예외(재시도는 호출부가)."""

        system = "\n\n".join(m[1] for m in messages if m[0] == "system")
        human = "\n\n".join(m[1] for m in messages if m[0] != "system")
        schema_json = json.dumps(self._schema.model_json_schema(), ensure_ascii=False)
        prompt = (
            f"{system}\n\n---\n[입력]\n{human}\n\n---\n"
            "위 지시에 따라 결과를 아래 JSON Schema 에 맞는 **JSON 하나만** 출력하라. "
            "설명·코드펜스·다른 텍스트를 붙이지 마라. 스키마의 description 은 각 필드를 "
            f"어떻게 채울지에 대한 지시다.\n[JSON Schema]\n{schema_json}"
        )

        wrapper = _run_cli(self._chat.cli, self._chat.model, prompt)
        return self._schema.model_validate_json(extract_json(str(wrapper.get("result") or "")))
