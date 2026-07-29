"""골든셋 라벨링 CLI — 실제 판단은 사람이 한다. 도구는 빠르게 라벨만 받는다.

사용: python run_label.py            # 미라벨 항목부터 순서대로
      python run_label.py q19        # 특정 질의만
      python run_label.py --resume   # 중단 지점부터 (기본 동작과 동일, 명시용)

키: c=Correct  a=Ambiguous  i=Incorrect  s=skip(미결정, 다음에 다시 물음)
    p=이 질의의 expected_parsed 확인/수정  q=저장 후 종료
매 응답마다 즉시 저장하므로 언제 중단해도 안전하다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

POOL = Path(__file__).resolve().parent / "golden" / "pool.json"
LABELS = {"c": "Correct", "a": "Ambiguous", "i": "Incorrect"}


def load():
    return json.loads(POOL.read_text(encoding="utf-8"))


def save(data):
    POOL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def progress(data):
    total = sum(len(v["candidates"]) for v in data.values())
    done = sum(1 for v in data.values() for c in v["candidates"] if c["label"] is not None)
    return done, total


def edit_parsed(qid, entry):
    print(f"  현재: {entry['expected_parsed']}")
    raw = input("  수정할 JSON (엔터=그대로 확정): ").strip()
    if raw:
        try:
            entry["expected_parsed"] = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  파싱 실패, 유지: {e}")
    entry["parsed_verified"] = True


def label_query(qid, entry, data):
    print(f"\n{'='*70}\n[{qid}] {entry['query']!r}  ({entry['category']})")
    print(f"  expected_parsed: {entry['expected_parsed']}"
          + ("" if entry["parsed_verified"] else "  <- 미확인, p로 검토"))

    for c in entry["candidates"]:
        if c["label"] is not None:
            continue
        while True:
            exp = "무관" if c["exp_min"] is None else f"{c['exp_min']}년+"
            loc = ", ".join(c["regions"][:2]) or "미상"
            print(f"\n  {c['company']} | {c['title']}")
            print(f"  [{exp} · {loc}] 기술: {', '.join(c['tech'][:6])}")
            print(f"  {c['snippet']}")
            ans = input("  [c=Correct a=Ambiguous i=Incorrect s=skip p=parsed수정 q=저장종료] > ").strip().lower()
            if ans == "q":
                save(data)
                print("저장 완료.")
                sys.exit(0)
            if ans == "p":
                edit_parsed(qid, entry)
                save(data)
                continue
            if ans == "s":
                break
            if ans in LABELS:
                c["label"] = LABELS[ans]
                save(data)
                break
            print("  ? c/a/i/s/p/q 중 하나를 입력해줘.")


def main():
    data = load()
    args = [a for a in sys.argv[1:] if a != "--resume"]
    qids = args or list(data.keys())

    done, total = progress(data)
    print(f"진행 상황: {done}/{total} 라벨링됨")

    for qid in qids:
        if qid not in data:
            print(f"질의 {qid} 없음, 건너뜀")
            continue
        entry = data[qid]
        if all(c["label"] is not None for c in entry["candidates"]):
            continue
        label_query(qid, entry, data)

    save(data)
    done, total = progress(data)
    print(f"\n완료: {done}/{total}")


if __name__ == "__main__":
    main()
