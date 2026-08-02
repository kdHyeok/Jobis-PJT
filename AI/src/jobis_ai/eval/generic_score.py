"""제네릭 점수 — **답변이 그 공고에서만 나올 수 있는 것인지** 잰다.

기존 하네스가 재는 것: 플래너가 누구를 부르나(`planner_harness`), 궤적이 흔들리나
(`consistency`·`loop_consistency`). 아무도 재지 않던 것: **답의 내용.**

D101 이 그 구멍을 드러냈다. 승격(D97) 케이스 중 하나는 승격 **전 어휘로도** 통과했다 —
같은 담당에게 갔어도 전에는 요약만 냈고 지금은 학습 순서·프로젝트를 답하는데, 그 차이를
플래너 하네스는 원리적으로 못 본다. 외부 리뷰의 지적도 같은 표면이었다: "제안된 세 프로젝트는
거의 모든 AI/데이터 공고에 그대로 나올 답이다."

## 원시 유사도만 재면 해석할 수 없는 숫자가 된다

서로 다른 공고 N개에 같은 질문을 던져 답변 쌍의 코사인 유사도를 재는 것이 출발점이다.
그런데 **비슷한 공고 둘이 비슷한 답을 받는 것은 정상이다** — AI 공고와 데이터 공고는 실제로
요구가 겹친다. 그 정상분을 빼지 않으면 "0.82" 가 좋은 건지 나쁜 건지 말할 수 없고, 지표는
올리기만 하는 숫자가 된다(D101 이 경고한 거울).

그래서 **공고 유사도를 같이 재서 뺀다**:

    delta(i,j) = sim(답변i, 답변j) - sim(공고i, 공고j)

  · delta ≈ 0   → 답변이 공고만큼 갈린다. 공고를 실제로 읽었다는 뜻이다.
  · delta 크게 > 0 → **공고는 다른데 답이 같다 = 제네릭.** 이게 잡으려는 결함이다.
  · delta < 0   → 답이 공고보다 더 갈린다(질문·요건 인용이 많을 때 정상).

`generic_score` 는 delta 의 쌍 평균이다. **낮을수록 좋다.** 절대 임계값을 코드에 박지
않는다 — 임계는 모델·프롬프트마다 달라서, 지금 필요한 것은 **개선 전후를 비교할 수 있는 축**이고
기준선은 baseline 파일이 맡는다(§3-2 "매번 잰다").

## 무엇을 실행하나

`posting_analysis.run(session)` 을 직접 부른다 — 라우팅은 `planner_harness` 가 이미 재므로
여기서는 **답변만** 본다(플래너 변동이 지표에 섞이지 않는다). 세션은 공고 + 발화뿐이고
이력서는 넣지 않는다: 이력서가 있으면 답이 개인화돼 공고 간 차이가 흐려진다.

임베딩이 미연결이면 **점수를 만들지 않고 그렇다고 말한다**(§2-1). 지어낸 0.0 은 개선으로 읽힌다.
"""

from __future__ import annotations

import argparse
import json
import time
from itertools import combinations
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
_DATASET = _ROOT / "evals" / "generic_dataset.json"

# 답변에서 유사도 계산에 쓰는 최대 길이 — 임베딩 입력 상한 방어. 앞부분에 결론이 온다.
_MAX_CHARS = 4000

# **답변에서도** 우리가 넣은 뼈대를 걷어낸다. 공고 쪽만 걷어내면 비대칭이고,
# 그 비대칭이 delta 를 답변 쪽으로 부풀린다. 실측(2026-08-01, 8공고): 답변 8개의 내용은 완전히
# 도메인별로 갈렸는데(OWASP/DVWA vs Swift/StoreKit/XCTest) 답변 유사도가 0.6161 로 공고 유사도
# (0.5122)보다 높았다. 겹치는 것은 내용이 아니라 **`save_plan` 산출물을 조립할 때 우리가 붙이는
# 라벨**이었다 — "프로젝트 제안 / 커버하는 요건: / 완료 기준:" 이 제안 수만큼(3~4회) 반복된다.
#
# **제품에서 라벨을 빼는 것은 답이 아니다** — 그 라벨은 사용자가 근거를 확인하는 장치다(D104).
# 고칠 곳은 지표다: 양쪽에서 같은 규칙으로 뼈대를 걷어낸다.
_ANSWER_SCAFFOLD = ("프로젝트 제안", "커버하는 요건:", "완료 기준:")


def _content_only(answer: str) -> str:
    """답변에서 **우리가 삽입한 라벨**만 지운다 — 공고 쪽 `requirement_baseline_text` 의 짝.

    LLM 이 스스로 쓴 문장(도입부·학습 순서 서술)은 **건드리지 않는다.** 그것이 같으면 실제로
    같은 답을 쓴 것이고, 지표가 잡아야 하는 대상이다. 지우는 것은 조립 코드가 붙인 고정 문자열뿐이다.
    """

    out = answer or ""
    for token in _ANSWER_SCAFFOLD:
        out = out.replace(token, " ")
    return " ".join(out.split())


# `offPostingSkillRate` 를 계산하려면 공고에 **비교할 기술 어휘**가 있어야 한다. 이보다 적으면
# 분모가 없는 것이라 비율을 만들지 않는다(아래 함수 주석의 보안 공고 실측).
_MIN_POSTING_SKILLS = 3


def requirement_baseline_text(parsed: dict) -> str:
    """파싱된 공고 → **요구사항만** 이어붙인 문자열. 기준선(공고 유사도)의 입력이다.

    **왜 원문이 아니라 파서 산출인가**(D108): 처음에는 원문에서 서식 낱말을 지워 썼는데
    (`_requirements_only`), 실공고로 바꾸자 그 방식이 무너졌다 — 실측(2026-08-01): 공고 유사도가
    합성 8공고 0.5122 → 실공고 8건 **0.5525** 로 **올라갔다.** 실공고에는 회사 소개·복리후생·
    근무조건·지원방법이 길게 붙고 그 부분이 직무와 무관하게 닮았는데, 섹션 제목 낱말만 지우는
    필터로는 걷어낼 수 없었다. 부풀린 기준선을 delta 에서 빼면 **지표가 관대해진다.**

    파서는 이미 요구사항을 항목으로 뽑아 둔다. 그것만 비교하는 것이 **"공고의 요구가 얼마나
    다른가"의 정확한 정의**다 — 상용구는 애초에 들어오지 않는다. 새 추출기를 만들지 않고
    파이프라인 산출을 그대로 쓴다.

    **어느 칸을 넣는가 — 답변 쪽 근거(`tool_render.posting_facts`)와 대칭이어야 한다.**
    첫 구현은 `requiredRequirements`+`preferredRequirements`+`techStack` 만 이어붙였는데,
    실측(2026-08-01)에서 `mobile-flutter` 공고의 기준선이 **64자**로 나왔다. 원문을 열어 보니
    자격요건이 "학력무관" 한 줄뿐이고, 그 공고를 실제로 가르는 정보(**Flutter 개발자**,
    **IoT·가전·헬스케어·고급 아파트**)는 담당업무 서술에 있었다 — 그리고 파서는 그것을 이미
    `jobTitle`·`domainKeywords` 로 정형화해 두고 있었다. **새 스키마 칸이 필요한 게 아니라
    내가 있는 칸을 안 썼던 것이다.**

    답변 쪽 facts 에는 `jobTitle`·`domainKeywords`·연차가 다 들어간다. 기준선이 답변보다 정보가
    적으면 delta 가 왜곡되므로 같은 칸을 넣는다.

    **회사명은 넣지 않는다.** 요구가 아니라 신원이고, 회사명이 서로 완전히 달라 기준선을
    인위적으로 낮춘다(= 지표를 엄격한 쪽으로 오염시킨다). `rawChunks` 도 쓰지 않는다 —
    파서가 상태 비대화 방지로 비우고, 원문 조각은 상용구를 다시 들인다.
    """

    parts: list[str] = [str(parsed.get("jobTitle") or "").strip()]
    for key in ("requiredRequirements", "preferredRequirements"):
        parts += [str(r.get("text") or "").strip() for r in (parsed.get(key) or [])]
    parts += [str(t).strip() for t in (parsed.get("techStack") or [])]
    parts += [str(k).strip() for k in (parsed.get("domainKeywords") or [])]
    # 연차도 요구다 — 공고가 한 말(yearsEvidence)을 그대로 쓴다(사다리 라벨은 손실 요약이다).
    parts.append(str(parsed.get("yearsEvidence") or "").strip())
    return "\n".join(x for x in parts if x)


def parse_baseline(postings: list[dict]) -> tuple[list[str], list[dict]]:
    """공고를 **LLM 으로 파싱**해 기준선 텍스트를 만든다. (기준선 텍스트들, 경고)

    이건 `--refresh-baseline` 에서만 부른다. 측정 때는 `posting_baseline` 이 데이터셋에 **박아 둔
    값**을 읽는다 — 아래 그 함수의 주석이 이유다.
    """

    from jobis_ai.agents import posting_analysis

    texts: list[str] = []
    warnings: list[dict] = []
    for posting in postings:
        _parsed, data, _updates, warns, _text = posting_analysis._parse(
            {"job_posting": {"sourceType": "text", "value": posting["text"]}})
        warnings.extend(warns)
        baseline = requirement_baseline_text(data.get("postingAnalysis") or {})
        if not baseline:
            warnings.append({"code": "posting_baseline_empty",
                             "message": f"{posting['id']}: 요구사항을 못 읽어 기준선이 비었습니다"})
        texts.append(baseline)
        print(f"    기준선 파싱 {posting['id']:16} 요건 {len(baseline):5}자", flush=True)
    return texts, warnings


def posting_baseline(postings: list[dict]) -> tuple[list[str], list[dict]]:
    """데이터셋에 **박아 둔** 기준선 텍스트를 읽는다. (기준선 텍스트들, 경고)

    **왜 매번 파싱하지 않는가 — 기준선은 상수여야 한다(D109).** 처음에는 측정마다 여기서 LLM 으로
    다시 파싱했다. 그러면 같은 공고인데 기준선이 측정마다 달라지고, delta 는 답변에서 뺀 값이므로
    **답변이 하나도 안 변해도 점수가 움직인다.** 실측(2026-08-01, 같은 8공고·같은 코드):

        runs=3 → 기준선 공고 유사도 0.5271 · 답변 0.5290 → delta +0.0019
        runs=5 → 기준선 공고 유사도 0.5156 · 답변 0.5498 → delta +0.0341

    delta 가 +0.032 움직였는데 그중 **0.0115(3분의 1)는 기준선이 내려간 몫**이었다. 측정 장치가
    측정 대상만큼 흔들리면 어떤 전후 비교도 성립하지 않는다 — 파싱은 읽기 계층이라 LLM 이 맞지만
    (§1), 그 산출을 **측정의 눈금자로 쓸 때는 한 번 뽑아 고정해야** 한다.

    갱신은 명시로만: `--refresh-baseline`. 공고를 바꾸거나 파서를 고쳤으면 그때 다시 뽑고, 눈금자가
    바뀌었으므로 **이전 baseline 과 비교하지 않는다**(기록에 그렇게 적는다).
    """

    texts: list[str] = []
    warnings: list[dict] = []
    for posting in postings:
        baseline = str(posting.get("baselineText") or "")
        if not baseline:
            warnings.append({
                "code": "posting_baseline_missing",
                "message": f"{posting['id']}: 데이터셋에 baselineText 가 없습니다 — "
                           "`--refresh-baseline` 으로 먼저 뽑으십시오"})
        texts.append(baseline)
    if any(w["code"] == "posting_baseline_missing" for w in warnings):
        # 일부만 비어 있으면 유사도가 조용히 왜곡된다(빈 문자열끼리는 비슷하다). 멈춘다.
        raise SystemExit("기준선이 비어 있는 공고가 있습니다 — "
                         "`python -m jobis_ai.eval.generic_score --refresh-baseline` 먼저.")
    return texts, warnings


def refresh_baseline(path: str | Path) -> None:
    """공고를 파싱해 `baselineText` 를 데이터셋에 **박는다.** 눈금자를 다시 만드는 유일한 경로."""

    file = Path(path)
    data = json.loads(file.read_text(encoding="utf-8"))
    texts, warnings = parse_baseline(data["postings"])
    for posting, text in zip(data["postings"], texts):
        posting["baselineText"] = text
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n기준선 {len(texts)}건을 {file} 에 고정했습니다."
          f"  경고 {_codes(warnings) or '없음'}")
    print("**눈금자가 바뀌었습니다 — 이전 baseline 과 직접 비교하지 마십시오**(D109).")


def off_posting_skill_rate(answer: str, posting_text: str) -> float | None:
    """답변이 언급한 기술 중 **그 공고에 없는** 것의 비율. 없으면 None(스킬을 못 찾음).

    **임베딩 지표의 짝이다.** 실측(2026-08-01): `key-requirement` 답변 네 개는 각 공고의 요건을
    정확히 인용했는데도 유사도가 높게 나왔다 — 내용이 아니라 **문장 틀**("가장 중요한 요건은
    필수 요건 3가지입니다 / … / 우대 사항(…)은 …")이 같았고, 답변이 짧아 틀이 임베딩을
    지배했다. 그 지표만 쓰면 **표현만 바꿔서 점수를 올릴 수 있다**(Goodhart).

    이 비율은 틀에 면역이다 — 어떻게 말했는지가 아니라 **어느 공고의 기술을 말했는지**만 본다.
    0 에 가까울수록 그 공고를 읽고 답했다는 뜻이고, 크면 공고에 없는 기술을 끌어온 것이다
    (제네릭·환각 방향). `skill_taxonomy` 를 그대로 쓴다 — 새 사전을 만들지 않는다.

    **0 이 아닌 것 자체는 결함이 아니다(중요).** 실측(2026-08-01)에서 걸린 두 건은
    `EC2`(공고는 "AWS/GCP/Azure 중 하나")와 `Redux`(공고는 "상태 관리 라이브러리 사용 경험")
    였다 — 둘 다 환각이 아니라 **추상 요건의 정당한 구체화**다. 학습·프로젝트를 제안하려면
    구체적인 도구 이름이 필요하다. 이 지표를 "0 이어야 한다"로 읽으면 다음 사람이 Redux 를
    지워서 답을 **더 나쁘게** 만든다.

    쓰는 법: **절대값이 아니라 변화**를 본다. 그리고 값이 크게 튀었을 때 `answers` 를 열어
    구체화인지 표류인지 사람이 가른다 — 그래서 답변을 결과에 남긴다.
    """

    from jobis_ai.skill_taxonomy import get_skill_taxonomy

    taxonomy = get_skill_taxonomy()
    in_answer = taxonomy.find_in_text(answer)
    if not in_answer:
        return None
    in_posting = {s.lower() for s in taxonomy.find_in_text(posting_text)}
    # **공고의 기술 어휘가 빈약하면 비율이 의미를 잃는다.** 실측(2026-08-01, 8공고): 보안 공고는
    # taxonomy 가 아는 기술이 **0개**였고(OWASP·ISMS-P 는 사전에 없다) 그 결과 답변의 모든 기술이
    # "밖"으로 잡혀 rate 가 1.0 이 됐다 — 답변 결함이 아니라 분모가 없는 것이다. 그 값이 전체
    # 평균을 끌어올려(0.14) 품질 수치처럼 보였다. 모르면 점수를 만들지 않는다(§2-1).
    if len(in_posting) < _MIN_POSTING_SKILLS:
        return None
    off = [s for s in in_answer if s.lower() not in in_posting]
    return round(len(off) / len(in_answer), 4)


def _answer(posting_text: str, question: str) -> tuple[str, list[dict]]:
    """공고 하나 + 질문 하나 → 공고 담당의 답변. (답변, 경고)"""

    from jobis_ai.agents import posting_analysis

    session: dict[str, Any] = {
        "job_posting": {"sourceType": "text", "value": posting_text},
        "last_message": question,
    }
    outcome = posting_analysis.run(session)
    return (outcome.reply or "").strip()[:_MAX_CHARS], list(outcome.warnings)


def _pairwise(texts: list[str], labels: list[str]) -> dict[str, float] | None:
    """쌍별 코사인 유사도. 임베딩 미연결이면 None(0.0 을 지어내지 않는다)."""

    from jobis_ai.embed import get_embedder

    matrix = get_embedder().similarity_matrix(texts, texts)
    if not matrix:
        return None
    return {
        f"{labels[i]}|{labels[j]}": round(float(matrix[i][j]), 4)
        for i, j in combinations(range(len(texts)), 2)
    }


def score_question(question: dict, postings: list[dict],
                   posting_sim: dict[str, float] | None,
                   progress: str = "") -> dict[str, Any]:
    """질문 하나에 대해 공고 전체를 돌려 delta 를 낸다.

    **한 실행마다 진행을 인쇄한다**(`flush=True`). 8공고 × 질문 2 × 3회 = 48실행이 20분 넘게
    도는데 끝까지 아무 출력이 없어서, 돌고 있는지 멈춘 건지 밖에서 알 수 없었다(2026-08-01).
    출력이 없는 도구는 모니터링해도 볼 것이 없다 — 관찰 가능성은 도구가 만든다.
    """

    labels = [p["id"] for p in postings]
    answers: list[str] = []
    warnings: list[dict] = []
    empty: list[str] = []
    total = len(postings)
    for index, posting in enumerate(postings, start=1):
        started = time.monotonic()
        reply, warns = _answer(posting["text"], question["text"])
        answers.append(reply)
        warnings.extend(warns)
        if not reply:
            empty.append(posting["id"])
        print(f"    {progress}[{index}/{total}] {posting['id']:16} "
              f"{len(reply):5}자 {time.monotonic() - started:5.1f}초"
              + ("  ⚠ 빈 답변" if not reply else ""), flush=True)

    # 틀에 면역인 짝 지표 — 공고에 없는 기술을 끌어왔는지.
    off_rates = {labels[i]: off_posting_skill_rate(answers[i], postings[i]["text"])
                 for i in range(len(answers))}
    measured_rates = [v for v in off_rates.values() if v is not None]

    answer_sim = _pairwise([_content_only(a) for a in answers], labels)
    if answer_sim is None or posting_sim is None:
        return {
            "questionId": question["id"], "measured": False,
            "reason": "임베딩 미연결 — 유사도를 계산할 수 없다(점수를 만들지 않는다)",
            "emptyAnswers": empty, "warningCodes": _codes(warnings),
            "offPostingSkillRate": off_rates,
        }

    deltas = {key: round(answer_sim[key] - posting_sim[key], 4) for key in answer_sim}
    worst = max(deltas, key=lambda k: deltas[k])
    return {
        "questionId": question["id"], "measured": True,
        # 낮을수록 좋다 — 답변이 공고만큼 갈린다는 뜻.
        "genericScore": round(sum(deltas.values()) / len(deltas), 4),
        "meanAnswerSim": round(sum(answer_sim.values()) / len(answer_sim), 4),
        "meanPostingSim": round(sum(posting_sim.values()) / len(posting_sim), 4),
        "worstPair": worst, "worstDelta": deltas[worst],
        # 공고에 없는 기술을 끌어온 비율 — 임베딩 유사도와 달리 **문장 틀에 면역**이다.
        "offPostingSkillRate": off_rates,
        "meanOffPostingSkillRate": (round(sum(measured_rates) / len(measured_rates), 4)
                                    if measured_rates else None),
        "pairs": {k: {"answer": answer_sim[k], "posting": posting_sim[k], "delta": deltas[k]}
                  for k in answer_sim},
        "answerChars": [len(a) for a in answers],
        # **답변을 남긴다.** 수치만 있으면 사람이 "이 점수가 맞나"를 확인할 수 없고, 그러면
        # 지표가 근거 없이 신뢰받는다(§2-6 과 같은 원리 — 결론만 주고 이유를 삼키지 않는다).
        "answers": {labels[i]: answers[i] for i in range(len(answers))},
        # 빈 답변은 유사도를 왜곡한다(빈 문자열끼리는 비슷하다) — 숨기지 않는다.
        "emptyAnswers": empty,
        "warningCodes": _codes(warnings),
    }


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


def _codes(warnings: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for warn in warnings:
        code = str(warn.get("code") or "unknown")
        out[code] = out.get(code, 0) + 1
    return out


# 여러 측정의 **합동 표준편차** — 전후 비교 문턱이 여기서 나온다.
#
# **왜 측정마다 계산한 SEM 을 문턱으로 쓰지 않는가.** n=5 에서 σ 추정의 90% 구간은 참값의
# **×0.60~×2.37** 이다(χ², 자유도 4). 실측(2026-08-02)에서 같은 질문의 σ 가 두 측정에서
# 0.0091 과 0.0267 로 나왔는데(2.9배), 이건 노이즈가 변한 게 아니라 **추정의 오차 범위 안**이다.
# 문턱을 그때그때 SEM 으로 잡으면 문턱 자체가 3배 흔들리고, 그러면 "개선했다"의 기준이 매번 바뀐다.
#
# 그래서 문턱은 **측정 여러 개를 모은 합동 σ** 로 정한 상수로 쓴다. 지금 값의 출처(자유도 8,
# runs=5 측정 2회 — `evals/generic_baseline_real8_runs5.json`·`..._frozen.json`):
#
#     study-plan       σ 0.0091 · 0.0267 → 합동 0.0199   ← 큰 쪽을 쓴다
#     key-requirement  σ 0.0160 · 0.0080 → 합동 0.0126
#
# 갱신 규칙: 측정이 쌓이면 자유도를 늘려 다시 합동 계산하고 이 상수를 고친다(그때 근거를
# `docs/eval-records/` 에 남긴다). 답변 생성 코드가 바뀌면 노이즈 규모도 바뀌므로 다시 잰다.
_POOLED_SD = 0.0199


def comparison_threshold(runs: int) -> float:
    """전후 비교 문턱 = 2 × (합동 σ / √runs). 이보다 작은 차이는 개선이라 부를 수 없다.

    2배를 곱하는 이유: 전후 **두** 측정에 각각 불확실성이 있으니 보수적으로 잡는다.
    runs 를 늘리면 √runs 로 좁아진다 — runs=5 에서 0.0178, runs=20 이면 0.0089(비용 4배).
    """

    return round(2 * _POOLED_SD / (runs ** 0.5), 4)


def _spread(values: list[float]) -> dict[str, float]:
    """N회 값의 흩어짐. **문턱으로 쓰는 것은 `sem` 이고 `range` 가 아니다.**

    처음에는 `range`(max−min)를 "노이즈 바닥"으로 썼는데 **잘못이다** — 범위는 표본이 늘면
    커진다(극단을 만날 기회가 늘어서). 실측(2026-08-01): runs 3→5 로 늘렸더니 `key-requirement`
    의 범위가 0.0186 → 0.0375 로 **두 배가 됐고**, 그걸 보고 "표본을 늘려도 안 좁아진다"고
    잘못 판단했다. 같은 데이터의 SEM 은 study-plan 에서 0.0081 → **0.0041 로 반이 됐다** —
    runs 를 늘린 효과가 실제로 있었다.

    쓰는 법: 평균의 불확실성은 **SEM**(σ/√n)이다. 단 **이 측정의 SEM 을 문턱으로 쓰지 않는다** —
    n=5 의 σ 추정은 ×0.6~×2.4 로 흔들려서 문턱이 매번 바뀐다(`_POOLED_SD` 주석). 문턱은
    `comparison_threshold(runs)`, 여기 값들은 **진단용**이다(어느 회차가 튀었는지 볼 때).
    """

    import statistics

    n = len(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    return {"mean": round(sum(values) / n, 4),
            "min": round(min(values), 4), "max": round(max(values), 4),
            "range": round(max(values) - min(values), 4),
            "sd": round(sd, 4), "sem": round(sd / (n ** 0.5), 4), "n": n}


def score_question_runs(question: dict, postings: list[dict], runs: int,
                        posting_sim: dict[str, float] | None) -> dict[str, Any]:
    """같은 질문을 N회 돌려 평균과 **범위**를 낸다.

    실측(2026-08-01)에서 1회 측정으로 전후를 비교했더니 `save_plan` 을 쓰지도 않는 질문
    (`key-requirement`)이 +0.0800 → +0.1288 로 움직였다 — LLM 이 매번 다르게 쓰기 때문이다.
    **범위를 모르면 어떤 비교도 개선을 주장할 수 없다.** 그래서 평균만 내지 않고 범위를 함께 낸다.
    """

    attempts = []
    for run in range(1, runs + 1):
        print(f"  [{question['id']}] 회차 {run}/{runs}", flush=True)
        attempts.append(score_question(question, postings, posting_sim,
                                       progress=f"r{run} "))
    measured = [a for a in attempts if a["measured"]]
    if not measured:
        return {**attempts[0], "runs": runs}
    off = [a["meanOffPostingSkillRate"] for a in measured
           if a["meanOffPostingSkillRate"] is not None]
    return {
        "questionId": question["id"], "measured": True, "runs": runs,
        "genericScore": _spread([a["genericScore"] for a in measured]),
        "offPostingSkillRate": _spread(off) if off else None,
        "attempts": attempts,
    }


def run_dataset(path: str | Path = _DATASET, runs: int = 1) -> tuple[list[dict], dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    postings, questions = data["postings"], data["questions"]
    labels = [p["id"] for p in postings]
    print("기준선: 데이터셋에 고정된 요구사항 텍스트를 쓴다(D108·D109)", flush=True)
    baseline_texts, baseline_warnings = posting_baseline(postings)
    posting_sim = _pairwise([t[:_MAX_CHARS] for t in baseline_texts], labels)
    print(f"  기준선 공고 유사도 평균: "
          + (f"{sum(posting_sim.values()) / len(posting_sim):.4f}" if posting_sim
             else "측정 불가(임베딩 미연결)") + "\n", flush=True)
    if runs > 1:
        print(f"실행 예정: 공고 {len(postings)} × 질문 {len(questions)} × {runs}회 "
              f"= {len(postings) * len(questions) * runs}회\n", flush=True)
        results = [score_question_runs(q, postings, runs, posting_sim) for q in questions]
        measured = [r for r in results if r["measured"]]
        summary = {
            "postings": len(postings), "questions": len(questions), "runs": runs,
            "measured": len(measured),
            "genericScore": (round(sum(r["genericScore"]["mean"] for r in measured)
                                   / len(measured), 4) if measured else None),
            "meanOffPostingSkillRate": _mean(
                [(r.get("offPostingSkillRate") or {}).get("mean") for r in measured]),
            # **전후 비교 문턱** — 합동 σ 에서 나온 상수다(이 측정의 SEM 이 아니다).
            "comparisonThreshold": comparison_threshold(runs),
            "pooledSd": _POOLED_SD,
            # 아래 둘은 **진단용** — 문턱으로 쓰지 않는다.
            "maxSem": (round(max(r["genericScore"]["sem"] for r in measured), 4)
                       if measured else None),
            "maxRange": (round(max(r["genericScore"]["range"] for r in measured), 4)
                         if measured else None),
            "emptyAnswers": sorted({p for r in measured
                                    for a in r.get("attempts") or []
                                    for p in a.get("emptyAnswers") or []}),
        }
        return results, summary
    print(f"실행 예정: 공고 {len(postings)} × 질문 {len(questions)} "
          f"= {len(postings) * len(questions)}회\n", flush=True)
    results = [score_question(q, postings, posting_sim, progress="") for q in questions]
    measured = [r for r in results if r["measured"]]
    summary = {
        "postings": len(postings), "questions": len(questions),
        "measured": len(measured),
        "genericScore": (round(sum(r["genericScore"] for r in measured) / len(measured), 4)
                         if measured else None),
        "meanOffPostingSkillRate": _mean([r.get("meanOffPostingSkillRate") for r in results]),
        "emptyAnswers": sorted({p for r in results for p in r["emptyAnswers"]}),
    }
    return results, summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="제네릭 점수 — 답변이 그 공고에서만 나올 수 있는지 (실 LLM + 임베딩)")
    parser.add_argument("dataset", nargs="?", default=str(_DATASET))
    parser.add_argument("--runs", type=int, default=1,
                        help="질문당 실행 횟수. 2 이상이면 **SEM** 을 함께 낸다 — "
                             "그걸 모르면 전후 비교로 개선을 주장할 수 없다")
    parser.add_argument("--save", help="baseline 저장 경로 — 콘솔에서 사라지는 수치는 baseline 이 못 된다")
    parser.add_argument("--refresh-baseline", action="store_true",
                        help="공고를 파싱해 기준선을 데이터셋에 다시 박고 끝낸다(눈금자 갱신·D109)")
    args = parser.parse_args()

    if args.refresh_baseline:
        refresh_baseline(args.dataset)
        return

    from jobis_ai.eval import provenance

    meta = provenance(dataset=args.dataset, runs=args.runs)
    results, summary = run_dataset(args.dataset, runs=args.runs)
    print(f"=== 제네릭 점수 — 공고 {summary['postings']}개 × 질문 {summary['questions']}개 "
          f"(provider={meta['provider']} model={meta['model']})")
    print("    genericScore = mean(답변 유사도 - 공고 유사도). **낮을수록 좋다**"
          " — 0 근처면 답변이 공고만큼 갈린다는 뜻.\n")

    for r in results:
        if not r["measured"]:
            print(f"  [{r['questionId']}] 측정 불가 — {r.get('reason')}")
            continue
        if r.get("runs", 1) > 1:
            g, o = r["genericScore"], r["offPostingSkillRate"]
            print(f"  [{r['questionId']}] genericScore {g['mean']:+.4f}"
                  f"  **SEM {g['sem']:.4f}** (σ {g['sd']:.4f}, n={g['n']})"
                  f"  · 진단용 범위 {g['min']:+.4f}~{g['max']:+.4f}(폭 {g['range']:.4f})")
            print("      공고 밖 기술 비율: "
                  + (f"{o['mean']:.4f} 범위 {o['min']:.4f}~{o['max']:.4f}" if o
                     else "측정 불가"))
            continue
        print(f"  [{r['questionId']}] genericScore {r['genericScore']:+.4f}"
              f"  (답변 {r['meanAnswerSim']:.4f} / 공고 {r['meanPostingSim']:.4f})")
        print(f"      최악 쌍: {r['worstPair']} delta {r['worstDelta']:+.4f}"
              f"  · 답변 길이 {r['answerChars']}")
        off = r["meanOffPostingSkillRate"]
        print(f"      공고 밖 기술 비율: "
              + (f"{off:.4f} (0 이면 그 공고 기술만 말했다)" if off is not None
                 else "측정 불가(답변에서 기술을 못 찾음)")
              + f"  {r['offPostingSkillRate']}")
        if r["emptyAnswers"]:
            print(f"      ⚠ 빈 답변: {r['emptyAnswers']} — 유사도가 왜곡된다")
        if r["warningCodes"]:
            print(f"      경고: {r['warningCodes']}")

    print()
    if summary.get("comparisonThreshold") is not None:
        print(f"**전후 비교 문턱 {summary['comparisonThreshold']:.4f}**"
              f" (= 2 × 합동σ {summary['pooledSd']:.4f} / √{summary['runs']})"
              " — 이보다 작은 차이는 개선이라 부를 수 없다.")
        print(f"  진단용: 이 측정의 최대 SEM {summary['maxSem']:.4f} · 최대 범위"
              f" {summary['maxRange']:.4f} — **둘 다 문턱으로 쓰지 않는다**"
              "(n=5 의 σ 추정은 ×0.6~×2.4 로 흔들리고, 범위는 표본이 늘면 커진다)")
    if summary["genericScore"] is None:
        print("전체: 측정 불가(임베딩 미연결) — 점수를 만들지 않는다")
    else:
        print(f"전체 genericScore: {summary['genericScore']:+.4f}"
              f"  ·  공고 밖 기술 비율 {summary['meanOffPostingSkillRate']}")
    if summary["emptyAnswers"]:
        print(f"⚠ 빈 답변이 있는 공고: {summary['emptyAnswers']}")

    if args.save:
        Path(args.save).write_text(
            json.dumps({"meta": meta, "summary": summary, "results": results},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nbaseline 저장: {args.save}")


if __name__ == "__main__":
    main()
