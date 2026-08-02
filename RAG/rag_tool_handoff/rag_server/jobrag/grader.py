"""CRAG 평가자(evaluator) — 검색결과를 생성부에 넘기기 전에 관련성을 검증한다.

존재 이유
---------
CRAG의 평가자는 랭킹을 개선하는 장치가 **아니다**. 검색이 무엇을 물어와도 생성부는
그것을 근거로 "이 공고가 맞습니다"라고 자신 있게 쓴다 — 이게 RAG의 환각 경로다.
평가자는 그 사이에 서서 두 가지를 한다:

  1. **환각 억제**  — 질의와 무관한 문서(INCORRECT)를 생성부에 **넘기지 않는다**.
     넘길 근거가 하나도 남지 않으면 답을 지어내는 대신 0건을 반환한다.
  2. **신뢰성 검증** — 통과시킨 문서마다 등급과 근거 한 문장을 남긴다.
     "왜 이 공고가 나왔는가"를 사후에 감사할 수 있어야 신뢰성 주장이 성립한다.

이 파일 이전 버전의 결함 (2026-07-30 수정)
------------------------------------------
  · `apply_correction`이 `pass`만 있는 빈 함수였다 — 채점 결과가 **아무것도 바꾸지 않았다**.
    즉 평가자가 존재하지 않는 것과 동일했다. 지금까지의 검색 지표는 순수 검색 성능이다.
  · 판정 입력에 **공고 본문이 없었다**. 회사·제목·연차·지역·기술 약 300자만 보고
    "이 문서로 질의에 답할 수 있는가"를 판정했다. 판정 대상이 아닌 것을 판정했다.
  · `classify()`의 max_tokens=20으로는 근거 문장이 잘려 나온다 → `judge()` 신설.
  · 등급이 순차 호출이었다(top_k=3이면 왕복 3회) → 병렬화.

정책 (되돌리려면 이 상수만 만지면 된다)
---------------------------------------
  DROP_INCORRECT   INCORRECT를 최종 반환에서 제외한다. False면 채점만 하고 통과시킨다
                   (= 이전 동작). 폐기된 항목은 버려지지 않고 응답의 `dropped`에 남는다.
  KEEP_AMBIGUOUS   AMBIGUOUS는 통과시키되 confidence="low"로 표시한다. 등급 정의상
                   "주제는 같고 세부가 부족"이므로 보여줄 값이 있다. 실측 근거도 있다 —
                   규칙 기반으로 직군·기술 불일치를 걸러내려 했을 때 불일치 254쌍 중
                   106쌍(41.7%)이 사람/판정자 기준 Correct였다. 애매를 버리면 손해다.
  FAIL_OPEN        LLM 호출·파싱 실패 시 그 문서를 **통과**시키고 verified=False를 붙인다.
                   평가자 장애가 검색 서비스를 멈추면 안 된다. 다만 "검증됨"이라고
                   말해서도 안 되므로 플래그로 구분한다.
"""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

from .generate import GmsClient
from .query_parser import QuerySpec
from .search import SearchHit

Grade = Literal["CORRECT", "AMBIGUOUS", "INCORRECT"]

DROP_INCORRECT = True
KEEP_AMBIGUOUS = True
FAIL_OPEN = True

# 재시도 정책. 실패 원인의 대부분이 429(quota)이고 즉시 재시도는 그대로 429이므로
# 지수 백오프를 둔다: 1차 실패 후 1.5초, 2차 실패 후 3초. 총 대기 최대 4.5초.
# 이보다 늘리면 사용자 대기가 길어지고, 줄이면 429를 못 넘긴다.
RETRIES = 3
BACKOFF_BASE_SEC = 1.5

# 문서당 1콜을 몇 개까지 동시에 던질지. **이 값이 곧 평가자의 QPS 배수다.**
# top_k=3에 4를 주면 검색 1건이 LLM 3콜을 동시에 낸다 — 429의 직접 원인이었다.
# 2로 낮춰 지연(직렬 대비 약 1.5배 단축)과 quota를 절충한다.
MAX_WORKERS = 2

# 본문 절단 상한. 계약 기본 top_k=3에서 3건 × 4천자 = 1.2만자로, 판정 1회당 부담이 크지 않다.
# 0이면 절단하지 않는다. 절단이 발생하면 판정 근거가 줄어드므로 응답에 truncated로 표시한다.
DOC_CHARS = 4000

# 평가자 프롬프트. 지시문을 영어로 두는 것은 의도적이다 — 등급 토큰(CORRECT/AMBIGUOUS/
# INCORRECT)이 그대로 출력돼야 파싱이 안정적이고, 한국어로 번역하면 모델이 등급명을
# 한국어로 바꿔 쓰는 사례가 생긴다. 판정 대상 텍스트(질의·공고)는 한국어 그대로 넣는다.
EVALUATOR_SYSTEM_PROMPT = """You are a strict and objective grading assistant. \
Your task is to evaluate the relevance of a retrieved document to a user's query.

Your goal is to determine if the retrieved document contains sufficient and relevant \
information to answer the user query. Do not evaluate based on your internal knowledge; \
rely ONLY on the provided document.

[Evaluation Criteria]
Evaluate the relationship between the query and the document, and classify it into \
exactly one of the following three categories:
1. "CORRECT": The document is highly relevant and contains specific information that \
directly answers the query.
2. "INCORRECT": The document is completely unrelated to the query, or it is impossible \
to answer the query using this document.
3. "AMBIGUOUS": The document shares the same topic or keywords, but lacks the specific \
details required to fully answer the query.

[Output Format]
You MUST respond with a valid JSON object only. Do not include any other text, markdown \
formatting blocks, or explanations outside the JSON.
{
  "grade": "CORRECT" | "INCORRECT" | "AMBIGUOUS",
  "reason": "A one-sentence explanation of why you assigned this grade based on the criteria."
}"""

USER_TEMPLATE = """[Inputs]
- User Query:
{query}

- Retrieved Document:
{document}"""

# ── 프롬프트 변형 ──────────────────────────────────────────
#
# V0(위 프롬프트)는 사용자가 지정한 원본이며 **기본값이다.**
#
# V1을 만든 이유 (2026-07-30 실측): 서비스 top-3 180쌍에서 V0이 INCORRECT를
# **0건** 냈다. 라벨상 부적합 22건이 그 안에 있었는데도 전부 AMBIGUOUS로 갔다.
# 원인은 V0의 INCORRECT 정의가 "completely unrelated / impossible to answer"로
# 매우 좁다는 것 — 같은 IT 직군이면 주제가 겹치므로 완전 무관에 해당하지 않는다.
# V1은 그 정의를 **채용 도메인의 탈락 조건**으로 구체화한다. 판정 축(직군·연차)은
# 임의 선택이 아니라 `eval/JUDGING_CRITERIA.md`가 이미 쓰던 축이다.
#
# 채택 여부는 `eval/PREREG_evaluator_prompt.md`의 사전 기준으로만 결정한다.
_V1_CRITERIA = """
[Evaluation Criteria]
This is a job-posting recommendation system. Judge whether the posting is one the \
applicant could actually apply to.

1. "CORRECT": The posting's job role matches what the applicant is seeking, and the \
applicant meets the stated experience requirement.
2. "INCORRECT": Assign this if EITHER holds:
   (a) the posting's job role is a different role from the one the applicant seeks \
(e.g. applicant wants backend, the posting is for a hardware or sales role), OR
   (b) the applicant's years of experience fall short of the minimum the posting \
requires.
   Sharing a general topic (both being IT jobs, both mentioning Python) is NOT enough \
to avoid INCORRECT.
3. "AMBIGUOUS": The role is adjacent or partially overlapping (e.g. backend vs \
fullstack), or the posting does not state enough detail to decide.
"""

PROMPT_VARIANTS: dict[str, str] = {
    "V0": EVALUATOR_SYSTEM_PROMPT,
    "V1": EVALUATOR_SYSTEM_PROMPT.replace(
        EVALUATOR_SYSTEM_PROMPT[EVALUATOR_SYSTEM_PROMPT.index("[Evaluation Criteria]"):
                                EVALUATOR_SYSTEM_PROMPT.index("[Output Format]")],
        _V1_CRITERIA.strip() + "\n\n"),
}

# 활성 변형. **사전 기준을 통과하기 전까지 V0이다.**
ACTIVE_PROMPT = "V0"


def system_prompt(variant: str | None = None) -> str:
    return PROMPT_VARIANTS[variant or ACTIVE_PROMPT]


@dataclass
class Verdict:
    """문서 1건에 대한 판정. `ok=False`면 LLM 호출·파싱이 실패해 등급을 신뢰할 수 없다."""
    posting_uid: str
    grade: Grade
    reason: str
    ok: bool = True
    truncated: bool = False

    def to_dict(self) -> dict:
        d = {"grade": self.grade, "reason": self.reason, "verified": self.ok}
        if self.truncated:
            d["truncated"] = True
        return d


@dataclass
class Correction:
    """교정 결과. 무엇을 통과시켰고 무엇을 왜 버렸는지 전부 남긴다."""
    kept: list[SearchHit] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    n_correct: int = 0
    n_ambiguous: int = 0
    n_incorrect: int = 0
    n_failed: int = 0

    @property
    def all_rejected(self) -> bool:
        """검색은 뭔가 물어왔지만 통과한 게 하나도 없는 상태."""
        return not self.kept and bool(self.dropped)

    def summary(self) -> dict:
        return {"correct": self.n_correct, "ambiguous": self.n_ambiguous,
                "incorrect": self.n_incorrect, "failed": self.n_failed,
                "kept": len(self.kept), "dropped": len(self.dropped)}

    def no_direct_match_reason(self) -> str:
        """전부 탈락했을 때 사용자에게 돌려줄 사유. 판정 근거를 그대로 쓴다 —
        여기서 새 문장을 지어내면 그게 또 하나의 환각이다."""
        if not self.dropped:
            return ""
        heads = [d["reason"] for d in self.dropped[:3] if d.get("reason")]
        body = " / ".join(heads)
        return (f"검색된 {len(self.dropped)}건 모두 평가자가 질의와 무관하다고 판정했습니다."
                + (f" 근거: {body}" if body else ""))


# ── 판정 입력 구성 ─────────────────────────────────────────

def query_text_for_eval(spec: QuerySpec) -> str:
    """평가자에게 보여줄 질의.

    `spec.text`("백엔드 개발자 Java Spring MySQL")를 그대로 쓰지 않는다. 그건 BM25용
    토큰 나열이고, 판정자에게는 무엇이 직무이고 무엇이 기술인지 구분되지 않는다.
    필드를 라벨로 명시한다. **비어 있는 필드는 아예 적지 않는다** — "지역: 없음"처럼
    쓰면 판정자가 그 없음을 조건으로 오해한다.
    """
    lines = []
    role = (spec.role_category or "").strip()
    head = spec.text.strip()
    if head:
        lines.append(f"지원 희망 직무: {head}")
    if role and role not in head:
        lines.append(f"직군 분류: {role}")
    if spec.tech:
        lines.append(f"보유/희망 기술: {', '.join(spec.tech[:12])}")
    if spec.exp_years is not None:
        lines.append(f"지원자 경력: {spec.exp_years}년")
    if spec.regions:
        lines.append(f"희망 지역: {', '.join(spec.regions)}")
    return "\n".join(lines) or head


def document_text(hit: SearchHit, body: str | None) -> tuple[str, bool]:
    """판정 대상 문서. 구조화 필드 + **공고 원문**. (텍스트, 절단여부)를 돌려준다."""
    exp = "경력무관" if hit.exp_min is None else f"{hit.exp_min}년 이상"
    loc = ", ".join(hit.regions[:3]) or "지역 미상"
    tech = ", ".join(hit.tech[:12]) or "명시 없음"
    head = (f"회사: {hit.company}\n제목: {hit.title}\n"
            f"요구 경력: {exp}\n근무 지역: {loc}\n기술 스택: {tech}")
    text = (body or "").strip()
    truncated = False
    if DOC_CHARS and len(text) > DOC_CHARS:
        text, truncated = text[:DOC_CHARS], True
    if text:
        head += f"\n\n[공고 본문]\n{text}"
    return head, truncated


# ── 파싱 ───────────────────────────────────────────────────

_JSON_RE = re.compile(r"\{.*\}", re.S)
_GRADES: tuple[Grade, ...] = ("CORRECT", "AMBIGUOUS", "INCORRECT")


def parse_verdict(raw: str, uid: str) -> Verdict:
    """모델 출력 -> Verdict. 프롬프트가 JSON only를 요구해도 코드펜스가 붙어 오는
    경우가 있으므로 첫 `{`~마지막 `}`를 뽑아 파싱한다. 그래도 실패하면 등급 토큰만
    문자열로 찾는다. 둘 다 실패하면 ok=False (FAIL_OPEN 정책이 처리한다).

    주의: `"INCORRECT" in raw`를 먼저 보지 않으면 INCORRECT의 부분문자열인
    "CORRECT"에 먼저 걸린다. 이전 버전이 갖고 있던 순서 의존을 그대로 유지한다.
    """
    m = _JSON_RE.search(raw or "")
    if m:
        try:
            obj = json.loads(m.group(0))
            g = str(obj.get("grade", "")).strip().upper()
            if g in _GRADES:
                reason = str(obj.get("reason", "")).strip()
                return Verdict(uid, g, reason or "(근거 미제시)")
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    up = (raw or "").upper()
    for g in ("INCORRECT", "AMBIGUOUS", "CORRECT"):
        if g in up:
            return Verdict(uid, g, "(JSON 파싱 실패 — 등급 토큰만 인식)", ok=False)
    return Verdict(uid, "AMBIGUOUS", "(평가자 응답을 해석할 수 없음)", ok=False)


# ── 판정 ───────────────────────────────────────────────────

_client: GmsClient | None = None


def _get_client() -> GmsClient:
    global _client
    if _client is None:
        _client = GmsClient()
    return _client


def evaluate_hit(query: str, hit: SearchHit, body: str | None = None,
                 variant: str | None = None) -> Verdict:
    """질의-문서 1쌍을 평가한다. 호출 실패는 예외를 던지지 않고 ok=False로 돌린다.

    재시도 + 지수 백오프. 근거(2026-07-30 실측):
      · 같은 질의를 두 번 돌렸을 때 한 번은 3건 전부 성공, 한 번은 1건 실패 —
        실패가 문서 내용 때문이 아니라 일시적이다.
      · 사람 라벨 119쌍을 연속 평가했을 때 **39쌍(33%)이 429(quota exhausted)로 실패**했다.
        문서당 1콜이므로 평가자는 검색 1건당 LLM QPS를 top_k배로 올린다. 429는 즉시
        재시도해도 그대로 429다 — 그래서 backoff 없이는 재시도가 무의미하다.
    FAIL_OPEN 정책상 실패는 '통과'가 되므로, 백오프를 안 하면 **부하가 걸릴 때 검증되지
    않은 공고가 조용히 늘어난다.** 실패 자체는 `verified=False`로 반드시 드러낸다.
    """
    doc, truncated = document_text(hit, body)
    user = USER_TEMPLATE.format(query=query, document=doc)
    last = "(원인 미상)"
    for attempt in range(RETRIES):
        if attempt:
            time.sleep(BACKOFF_BASE_SEC * (2 ** (attempt - 1)))
        try:
            v = parse_verdict(_get_client().judge(system_prompt(variant), user),
                              hit.posting_uid)
        except Exception as e:  # noqa: BLE001 — 평가자 장애가 검색을 막으면 안 된다
            msg = str(e)
            last = ("(평가자 호출 실패: 429 quota — 평가자 QPS 초과)"
                    if "429" in msg else f"(평가자 호출 실패: {type(e).__name__})")
            continue
        if v.ok:
            v.truncated = truncated
            return v
        last = v.reason
    return Verdict(hit.posting_uid, "AMBIGUOUS", last, ok=False, truncated=truncated)


def evaluate_hits(query: str, hits: list[SearchHit],
                  bodies: dict[str, str] | None = None,
                  max_workers: int = MAX_WORKERS) -> dict[str, Verdict]:
    """여러 문서를 **병렬로** 평가한다.

    순차로 하면 top_k=3에 왕복 3회가 그대로 지연에 얹힌다. 판정은 문서 간 독립이므로
    (배치 프롬프트가 아니라 문서당 1콜) 병렬화해도 결과가 바뀌지 않는다 — 오히려
    배치 프롬프트는 같은 배치에 무엇이 들어가느냐로 라벨이 흔들린다는 것을 이미
    측정했다(같은 배치 κ=1.0 vs 재표집 κ=0.3983). 문서당 1콜은 그 흔들림이 없다.
    """
    if not hits:
        return {}
    bodies = bodies or {}
    n = min(max_workers, len(hits))
    with ThreadPoolExecutor(max_workers=n) as ex:
        verdicts = list(ex.map(
            lambda h: evaluate_hit(query, h, bodies.get(h.posting_uid)), hits))
    return {v.posting_uid: v for v in verdicts}


# ── 교정 ───────────────────────────────────────────────────

def apply_correction(hits: list[SearchHit],
                     verdicts: dict[str, Verdict]) -> Correction:
    """등급 -> 실제 동작. 여기가 평가자가 '작동하는' 지점이다.

        CORRECT    통과 (confidence high)
        AMBIGUOUS  통과 (confidence low)          ← KEEP_AMBIGUOUS
        INCORRECT  제외, dropped에 근거와 함께 기록  ← DROP_INCORRECT
        판정 실패   통과, verified=False            ← FAIL_OPEN

    순서는 건드리지 않는다. 평가자는 필터이고 재순위기가 아니다 — 등급으로 순위를
    바꾸면 검색 지표와 서비스 순위가 어긋나 무엇을 측정했는지 알 수 없게 된다.
    """
    c = Correction(verdicts=verdicts)

    def drop(h: SearchHit, v: Verdict) -> None:
        c.dropped.append({"posting_uid": h.posting_uid, "title": h.title,
                          "company": h.company, "grade": v.grade, "reason": v.reason})

    for h in hits:
        v = verdicts.get(h.posting_uid)
        if v is None:                     # 평가되지 않은 항목 — 통과시킨다
            c.kept.append(h)
            continue
        if not v.ok:
            c.n_failed += 1
            c.kept.append(h) if FAIL_OPEN else drop(h, v)
        elif v.grade == "CORRECT":
            c.n_correct += 1
            c.kept.append(h)
        elif v.grade == "AMBIGUOUS":
            c.n_ambiguous += 1
            c.kept.append(h) if KEEP_AMBIGUOUS else drop(h, v)
        else:                             # INCORRECT
            c.n_incorrect += 1
            drop(h, v) if DROP_INCORRECT else c.kept.append(h)
    return c


def confidence_of(v: Verdict | None) -> str:
    """통과한 문서에 붙일 신뢰도 라벨. 판정 없음/실패는 unverified다 —
    검증하지 않은 것을 high로 표시하면 그게 곧 거짓 신뢰다."""
    if v is None or not v.ok:
        return "unverified"
    return {"CORRECT": "high", "AMBIGUOUS": "low"}.get(v.grade, "unverified")


# ── 진입점 ─────────────────────────────────────────────────

def enabled() -> bool:
    """`JOBRAG_EVALUATOR=0`으로 끈다. 결정적 평가 하네스는 반드시 0으로 돌려야 한다 —
    켜두면 LLM 호출이 끼어들어 재현성이 깨진다."""
    return os.environ.get("JOBRAG_EVALUATOR", "1") != "0"


def evaluate_and_correct(conn, spec: QuerySpec,
                         hits: list[SearchHit]) -> Correction:
    """검색 결과를 평가하고 교정한다. 본문은 이 안에서 가져온다.

    `generate.fetch_bodies`를 재사용한다 — 생성부가 보는 컨텍스트와 평가자가 보는
    문서가 **같은 원천**이어야 "생성부에 넘길 만한가"라는 판정이 성립한다.
    """
    if not hits or not enabled():
        return Correction(kept=list(hits))
    from .generate import fetch_bodies
    bodies = fetch_bodies(conn, [h.posting_uid for h in hits]) if conn else {}
    verdicts = evaluate_hits(query_text_for_eval(spec), hits, bodies)
    return apply_correction(hits, verdicts)


if __name__ == "__main__":
    import sys
    from .store import connect
    from .spec_adapter import spec_from_input

    q = sys.argv[1] if len(sys.argv) > 1 else "백엔드 개발자"
    conn = connect()
    try:
        _, spec, _ = spec_from_input(conn, q)
        from .search import hybrid_search
        res = hybrid_search(conn, spec, top_k=3, allow_relax=True, use_rerank=True)
        print(f"질의(평가자가 보는 형태):\n{query_text_for_eval(spec)}\n")
        c = evaluate_and_correct(conn, spec, res.hits)
        print(f"요약 {c.summary()}\n")
        for h in res.hits:
            v = c.verdicts.get(h.posting_uid)
            mark = "통과" if any(k.posting_uid == h.posting_uid for k in c.kept) else "폐기"
            print(f"[{mark}] {v.grade if v else '-':10} {h.company} — {h.title[:40]}")
            if v:
                print(f"        {v.reason}")
        if c.all_rejected:
            print(f"\n0건 반환: {c.no_direct_match_reason()}")
    finally:
        conn.close()
