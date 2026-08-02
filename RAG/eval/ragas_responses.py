"""2-B 생성 응답 수집 — 프롬프트 팩 방출 / 답변 수거 (HANDOFF §2-B).

faithfulness·answer_relevancy는 '생성된 답변'을 재는 축이다. 지금 ragas_dataset.json의
response는 검색결과를 기계적으로 나열한 템플릿이라 근거성이 구조적으로 높게 나온다 —
성능이 아니라 하네스 확인값이다. 실제 생성 답변으로 교체해야 본측정이 된다.

측정 유효성을 위한 3가지 고정 (이걸 어기면 점수가 무의미해진다):

1. 컨텍스트 동일 — 생성기에 주는 [검색결과]는 ragas_dataset.json의 retrieved_contexts
   '그 문자열 그대로'다. RAGAS faithfulness가 채점할 근거와 생성기가 본 근거가 한 글자도
   달라선 안 된다. (운영 _format_context는 URL·요약 형식이 달라 여기서 쓰지 않는다)
2. 시스템 프롬프트 동일 — jobrag.generate.SYSTEM_PROMPT를 그대로 쓴다. 모델만 바꾸는
   단일 변수 비교여야 한다. 프롬프트까지 바꾸면 무엇이 점수를 움직였는지 알 수 없다.
3. 질의마다 새 대화 — 한 대화에서 15질의를 연달아 하면 앞 질의의 공고가 뒤 답변에
   새어나오고, RAGAS는 그걸 '근거 없는 주장'(환각)으로 센다. 측정이 망가진다.

실행:
    python -X utf8 -m eval.ragas_responses --emit
        -> agent_responses/PROMPTS.md (15블록) + ANSWERS_TEMPLATE.md

    python -X utf8 -m eval.ragas_responses --ingest --source claude-opus-4.6
        -> agent_responses/answers.md 를 읽어 ragas_dataset_<source>.json 생성

    python -X utf8 -m eval.ragas_responses --generate-production
        -> 운영 생성부(jobrag.generate, gemini-2.5-flash-lite)로 같은 컨텍스트에 생성
           -> ragas_dataset_production.json  (Claude판과 A/B 대조용)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).parent
DATASET_PATH = EVAL_DIR / "ragas_dataset.json"
OUT_DIR = EVAL_DIR / "agent_responses"
PROMPTS_PATH = OUT_DIR / "PROMPTS.md"
TEMPLATE_PATH = OUT_DIR / "ANSWERS_TEMPLATE.md"
ANSWERS_PATH = OUT_DIR / "answers.md"


def _system_prompt() -> str:
    from jobrag.generate import SYSTEM_PROMPT
    return SYSTEM_PROMPT


def _context_block(contexts: list[str]) -> str:
    return "\n\n".join(f"### 공고 {i}\n{c.strip()}"
                       for i, c in enumerate(contexts, 1))


def _one_prompt(sample: dict) -> str:
    """생성기에 그대로 붙여넣을 1건. 운영 시스템 프롬프트 + 데이터셋 원본 컨텍스트."""
    return (
        f"{_system_prompt()}\n\n"
        f"[검색결과]\n{_context_block(sample['retrieved_contexts'])}\n\n"
        f"[질문]\n{sample['question']}"
    )


# ── 방출 ───────────────────────────────────────────────

def emit() -> None:
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    samples = data["samples"]
    OUT_DIR.mkdir(exist_ok=True)

    head = f"""# RAGAS 2-B 생성 프롬프트 팩 ({len(samples)}건)

생성 대상: `ragas_dataset.json`의 질의 {len(samples)}종. 나온 답변으로 faithfulness /
answer_relevancy를 본측정으로 승격한다.

## 사용법 — 이 3가지를 꼭 지켜주세요

1. **질의마다 새 대화(새 채팅)에서** 실행하세요. 한 대화에서 연달아 하면 앞 질의의
   공고가 뒤 답변에 섞이고, 평가기가 그걸 환각으로 세서 점수가 망가집니다.
2. 각 블록의 `--- PROMPT SA0x ---` 아래 **전체를 그대로** 붙여넣으세요.
   (시스템 프롬프트 + 검색결과 + 질문이 한 덩어리입니다. 요약·수정하지 마세요)
3. 모델이 낸 **답변 텍스트만** `answers.md`에 옮겨주세요. 사고 과정이나 부연 설명은
   빼고, 사용자에게 보여줄 최종 답변만요.

답변은 `ANSWERS_TEMPLATE.md`를 복사해 `answers.md`로 저장하고 각 `### SA0x` 아래에
채워주세요. 그 파일명 그대로 두시면 제가 수거합니다.

> 참고: 운영 생성부(gemini-2.5-flash-lite)도 **똑같은 컨텍스트·똑같은 시스템 프롬프트로**
> 따로 돌립니다. 두 결과를 대조하면 "답변 품질의 병목이 검색인지 생성 모델인지"가 나옵니다.
> 그래서 프롬프트를 바꾸지 않는 게 중요합니다 — 모델만 다른 단일 변수 비교여야 합니다.

---
"""
    blocks = [head]
    for s in samples:
        blocks.append(
            f"\n## {s['qid']} — {s['question']}\n\n"
            f"```\n--- PROMPT {s['qid']} ---\n{_one_prompt(s)}\n```\n\n---\n"
        )
    PROMPTS_PATH.write_text("".join(blocks), encoding="utf-8")

    tmpl = ["# RAGAS 2-B 답변 수거\n\n",
            "각 헤더 아래에 모델의 최종 답변 텍스트만 붙여넣어 주세요. 헤더는 지우지 마세요.\n"]
    for s in samples:
        tmpl.append(f"\n### {s['qid']}\n\n(여기에 답변)\n")
    TEMPLATE_PATH.write_text("".join(tmpl), encoding="utf-8")

    total = sum(len(_one_prompt(s)) for s in samples)
    print(f"프롬프트 팩: {PROMPTS_PATH}")
    print(f"답변 템플릿: {TEMPLATE_PATH}")
    print(f"  {len(samples)}블록, 평균 {total // len(samples):,}자 "
          f"(질의당 대화 1개, 총 {len(samples)}개 대화)")


# ── 수거 ───────────────────────────────────────────────

def ingest(source: str) -> None:
    if not ANSWERS_PATH.exists():
        raise SystemExit(f"{ANSWERS_PATH} 없음 — ANSWERS_TEMPLATE.md를 채워 "
                         f"answers.md로 저장해 주세요.")
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    text = ANSWERS_PATH.read_text(encoding="utf-8")

    found = {}
    for m in re.finditer(r"^###\s+(SA\d+)\s*$(.*?)(?=^###\s+SA\d+\s*$|\Z)",
                         text, re.M | re.S):
        body = m.group(2).strip()
        if body and body != "(여기에 답변)":
            found[m.group(1)] = body

    missing = [s["qid"] for s in data["samples"] if s["qid"] not in found]
    for s in data["samples"]:
        if s["qid"] in found:
            s["response"] = found[s["qid"]]
            s["response_source"] = f"{source} (운영 시스템 프롬프트 + 동일 retrieved_contexts)"

    out = EVAL_DIR / f"ragas_dataset_{_slug(source)}.json"
    data["response_generator"] = source
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"수거 {len(found)}/{len(data['samples'])}건 -> {out}")
    if missing:
        print(f"  누락(템플릿 그대로): {', '.join(missing)} — 해당 샘플은 LLM 축에서 제외됩니다")
    print(f"실행: python -X utf8 -m eval.ragas_run --dataset {out.name}")


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", s).strip("-").lower()


# ── 운영 생성부로 같은 컨텍스트 생성 (A/B 대조군) ──────

def generate_production() -> None:
    """운영 생성부와 '같은 컨텍스트'로 생성한다.

    jobrag.generate.generate_answer는 SearchHit 리스트를 받아 자체 포맷으로 컨텍스트를
    만든다. 그러면 Claude판이 본 근거와 글자가 달라져 단일 변수 비교가 깨지므로,
    GmsClient._call을 직접 써서 동일 프롬프트를 넣는다.
    """
    import os
    import random
    import time

    from jobrag.generate import GmsClient

    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    client = GmsClient()
    model = os.environ.get("GMS_MODEL", "gemini-2.5-flash-lite")
    sysp = _system_prompt()

    n_fail = 0
    for s in data["samples"]:
        user = (f"[검색결과]\n{_context_block(s['retrieved_contexts'])}\n\n"
                f"[질문]\n{s['question']}")
        for attempt in range(4):
            try:
                s["response"] = client._call(sysp, user, max_tokens=800).strip()
                s["response_source"] = (f"{model} 운영 생성부 "
                                        f"(운영 시스템 프롬프트 + 동일 retrieved_contexts)")
                print(f"  {s['qid']}: {len(s['response']):,}자")
                break
            except Exception as e:
                if attempt < 3:
                    time.sleep(2 ** attempt + random.random())
                    continue
                n_fail += 1
                print(f"  {s['qid']}: 실패 — {e}")

    out = EVAL_DIR / "ragas_dataset_production.json"
    data["response_generator"] = f"{model} (운영 생성부)"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n생성 완료 (실패 {n_fail}건) -> {out}")
    print(f"실행: python -X utf8 -m eval.ragas_run --dataset {out.name}")


def main():
    args = sys.argv[1:]
    if "--emit" in args:
        emit()
    if "--generate-production" in args:
        generate_production()
    if "--ingest" in args:
        src = "unknown-model"
        if "--source" in args:
            src = args[args.index("--source") + 1]
        ingest(src)
    if not args:
        print(__doc__)


if __name__ == "__main__":
    main()
