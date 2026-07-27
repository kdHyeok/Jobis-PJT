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

    # 구조화 없이 부르는 경로는 현재 없다(모든 호출이 run_structured 경유).
    # 필요해지면 invoke() 를 추가하되, 반드시 검증 계층을 붙인다.


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

        out = subprocess.run(
            # --strict-mcp-config: 전역 설정의 MCP 서버를 로드하지 않는다 — 기동이 수 초
            # 빨라지고, 구조화 추출에 도구는 필요 없다.
            [*self._chat.cli, "-p", prompt, "--output-format", "json",
             "--model", self._chat.model, "--max-turns", "1", "--strict-mcp-config"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_CALL_TIMEOUT_SEC, stdin=subprocess.DEVNULL,
            # 레포 밖에서 실행 — 프로젝트 CLAUDE.md·설정·훅이 판정 프롬프트에 섞이지 않게.
            cwd=tempfile.gettempdir(),
        )
        if out.returncode != 0:
            raise RuntimeError(
                f"claude CLI 종료 코드 {out.returncode}: {(out.stderr or out.stdout)[:300]}"
            )

        wrapper = json.loads(out.stdout)
        if wrapper.get("is_error"):
            raise RuntimeError(f"claude CLI 오류 응답: {str(wrapper.get('result'))[:300]}")
        return self._schema.model_validate_json(extract_json(str(wrapper.get("result") or "")))
