"""공고 URL 수집 도구 — URL 자산을 원문 텍스트 자산으로 승격한다. **파싱은 하지 않는다.**

수집(I/O)과 파싱(읽기)을 가른다(D64). 수집이 제 단계를 가지면:
- 진행 UI·로그에 "공고 수집"이 제 이름으로 보인다 (전에는 파싱 단계 안에 숨어 있었다)
- 실패 대응(본문 붙여넣기·캡쳐 요청)이 이 도구의 표현 하나로 떨어진다
- 뒤 단계(posting_analysis·fit_analysis)는 수집을 전제하지 않아도 된다

**플래너에는 보이지 않는다**(AgentSpec.internal). 호출은 오케스트레이터가 결정론으로 한다 —
URL 자산이 미수집 상태면 실행 큐 맨 앞에 끼운다(chat.py). LLM 이 고를 판단이 아니라
자산 상태에서 따라 나오는 필연이고, manifest 를 건드리지 않아 플래너 재측정이 필요 없다.

뒤 소비자의 ensure_posting_text 는 안전망으로 남는다 — 멱등이라, 이 도구가 승격을 끝내면
그쪽은 no-op 이다.
"""

from __future__ import annotations

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import ensure_posting_text


def run(session: dict) -> AgentResult:
    """URL 자산 → 원문 승격. **도구다 — 말하지 않는다**(문장은 render 가 만든다)."""

    posting = session.get("job_posting") or {}
    if (posting.get("sourceType") or "text").lower() != "url":
        # 이미 원문(또는 텍스트 제출) — 오케스트레이터 규칙이 막지만, 방어적으로 no-op.
        return AgentResult(reply="", data={"fetched": True, "alreadyText": True})

    url = (posting.get("value") or "").strip()
    promoted, warnings = ensure_posting_text(session)
    fetched = bool(promoted and (promoted.get("sourceType") or "") == "text")
    return AgentResult(
        reply="",
        data={
            "fetched": fetched,
            "sourceUrl": url,
            "chars": len((promoted or {}).get("value") or "") if fetched else 0,
        },
        warnings=warnings,
        # 카드 질문은 결정론 — 수집 실패면 사용자가 대신 줄 수 있는 것을 청한다.
        followUpQuestions=([] if fetched else [{
            "field": "job_posting",
            "question": "공고 본문(자격요건·우대사항) 내용을 복사해 붙여넣어 주시겠어요?",
        }]),
    )
