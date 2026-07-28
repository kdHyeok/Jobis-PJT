"""성공판정 검사 셋 (task 08) — 수동 스윕의 자동화.

사용:
  python -m tests.checks          # 결정적 검사만 (크레딧 0, 빠름·안정)
  python -m tests.checks --live   # + 라이브 검사 (실 GMS 호출, 비결정성)

판정 원칙(design.md §8): **구조만** 검사. 정확 문자열·품질 assert 금지.
"""
import glob
import json
import sys

try:  # Windows 콘솔(cp949)에서도 이모지·한글 출력 안전하게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_PASS: list[str] = []
_FAIL: list[str] = []


def _check(name: str, cond: bool, note: str = "") -> None:
    ok = bool(cond)
    (_PASS if ok else _FAIL).append(name)
    tail = f"  ({note})" if note else ""
    print(f"  {'✅' if ok else '❌'} {name}{tail}")


def deterministic() -> None:
    """LLM 없이 코드 로직만 — 항상 같은 결과, 크레딧 0."""
    print("\n[결정적 검사] (크레딧 0)")

    # 기준 2·3 코어 — 조건엣지
    from agent.graph import _route_after_tools
    g = {"run_id": "t", "tools_called": ["load_posting", "analyze_gap"]}
    _check("route: level 상 → agent(검색 X)", _route_after_tools({**g, "level": "상"}) == "agent")
    _check("route: level 중 → auto_search", _route_after_tools({**g, "level": "중"}) == "auto_search")
    _check("route: level 하 → auto_search", _route_after_tools({**g, "level": "하"}) == "auto_search")
    _check("route: gap 아닌 툴 뒤 → agent",
           _route_after_tools({"run_id": "t", "tools_called": ["load_posting"], "level": None}) == "agent")

    # analyze_gap 채점 임계치 (task 06)
    from tools.analyze_gap import _level_of
    _check("level: score 0.80 → 상", _level_of(0.80) == "상")
    _check("level: score 0.50 → 중", _level_of(0.50) == "중")
    _check("level: score 0.20 → 하", _level_of(0.20) == "하")

    # 스키마 — Literal 강제
    import pydantic
    from schemas import GapResult
    try:
        GapResult(score=0.1, level="X", rationale="x")
        bad_ok = False
    except pydantic.ValidationError:
        bad_ok = True
    _check("schema: GapResult level='X' 거부", bad_ok)

    # load_posting (기준 4 코어)
    from schemas import Posting, SearchResult, ToolError
    from tools import load_posting, search_postings
    data = json.load(open(sorted(glob.glob("sample_data/db내 공고파일/*.json"))[0], encoding="utf-8"))
    real_url = data[0]["url"]
    _check("load_posting: 실 url → Posting", isinstance(load_posting(real_url), Posting))
    nf = load_posting("https://no-such/none")
    _check("load_posting: 없는 url → NOT_FOUND", isinstance(nf, ToolError) and nf.error == "NOT_FOUND")

    # search_postings (계약)
    r = search_postings("백엔드")
    _check("search: SearchResult 반환", isinstance(r, SearchResult))
    _check("search: top_k ≤ 3", len(r.postings) <= 3)
    scores = [p.score for p in r.postings]
    _check("search: score 내림차순", scores == sorted(scores, reverse=True))
    if r.postings:
        m = r.postings[0].match_reason
        _check("search: match_reason 3필드",
               all(hasattr(m, f) for f in ("matched_skills", "matched_keywords", "matched_fields")))
    _check("search: 없는 쿼리 → []", search_postings("존재안하는직군zzzq").postings == [])


def live() -> None:
    """실 GMS 호출 — 구조 불변식만 (비결정성 감안)."""
    print("\n[라이브 검사] (실 GMS 호출)")
    from agent import run_agent
    from preprocess import parse_resume
    from tools import search_postings

    profile = parse_resume("sample_data/이력서_이서현_프론트엔드.docx")
    url = search_postings("백엔드").postings[0].url

    r3 = run_agent(f"내 이력서로 이 공고에 지원하면 붙을 수 있을까? {url}", profile)
    _check("기준1: 시나리오3 → analyze_gap 호출", "analyze_gap" in r3.meta.tools_called,
           f"tools={r3.meta.tools_called}")
    inv = ("search_postings" in r3.meta.tools_called) == (r3.meta.level in ("중", "하"))
    _check("기준2·3: search 발동 ⟺ level 중/하", inv, f"level={r3.meta.level}")

    rn = run_agent("이 공고 갈 수 있어? https://www.jobkorea.co.kr/Recruit/GI_Read/00000000", profile)
    _check("기준4: 없는 URL → 크래시 없이 응답", bool(rn.reply) and "load_posting" in rn.meta.tools_called)

    _check("기준5: max_steps 이내 종료(정상 반환)", bool(r3.reply) and bool(rn.reply))


def main() -> int:
    deterministic()
    if "--live" in sys.argv:
        live()
    total = len(_PASS) + len(_FAIL)
    print(f"\n=== 결과: {len(_PASS)}/{total} PASS ===")
    if _FAIL:
        print("❌ 실패:", _FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
