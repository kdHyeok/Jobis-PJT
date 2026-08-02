"""평가 하네스 (설계 18장).

성능을 지표로 반복 개선하기 위한 계층. 두 부분으로 나뉜다.
- metrics: 이미 산출된 노드 출력에 대해 지표를 계산하는 **순수 함수**(LLM 불필요, 결정적, 테스트 가능).
- harness: 평가셋을 로드해 노드를 실행하고 지표를 집계·리포트하는 러너(실 LLM 사용).

`provenance()` 는 모든 하네스가 공유한다 — **수치가 어느 조건에서 나왔는지 파일이 스스로
말하게** 하는 최소 정보다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def provenance(**extra: Any) -> dict[str, Any]:
    """baseline 파일에 박을 측정 조건 — 프로바이더·모델·온도·시각.

    **이게 없어서 무엇이 깨졌나**: 하네스가 `settings.llm_model`(GMS 모델명)을 프로바이더와
    무관하게 기록해, Claude CLI 로 돌린 baseline 에 `"model": "gpt-4.1-mini"` 가 박혔다.
    날짜도 없어 "이 수치가 어느 프롬프트 시점의 것인가"를 파일로 확인할 수 없었다
    (평가 리포트 §4-3 이 지적한 provenance 결함). 모델을 `settings.active_model()` 에서
    받으므로 런타임이 실제로 부르는 모델과 **갈라질 수 없다.**

    프로바이더까지 적는 이유: 배포는 LLM API 고정이고 CLI 는 E2E 하네스다(D57). 두 경로의
    수치를 같은 표에 올리면 안 되므로 어느 쪽으로 쟀는지가 수치와 같은 파일에 있어야 한다.
    """

    from jobis_ai.config import get_settings

    settings = get_settings()
    return {
        "provider": settings.llm_provider,
        "model": settings.active_model(),
        "modelLight": settings.active_model("light"),
        "modelRouter": settings.active_model("router"),   # 플래너가 실제로 부르는 모델(D74)
        "temperature": settings.temperature,
        "measuredAt": datetime.now().isoformat(timespec="seconds"),
        **extra,
    }
