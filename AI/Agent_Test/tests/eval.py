"""Agent Eval (task 10) — 다중실행 일관성·궤적 검증.

사용: python -m tests.eval [--runs N]   (기본 N=3, 실 GMS 다수 호출 = 크레딧 큼)
- 케이스별 N회 실행 → 기대 궤적(tool 순서)·불변식 충족 **일관성** 집계 + 이탈 덤프.
- 구조·일관성만. 추천 품질 판정 X.
"""
import logging
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(level=logging.WARNING, format="%(message)s")
for _n in ("httpx", "agent"):
    logging.getLogger(_n).setLevel(logging.WARNING)


def _runs_arg() -> int:
    if "--runs" in sys.argv:
        i = sys.argv.index("--runs")
        if i + 1 < len(sys.argv):
            return int(sys.argv[i + 1])
    return 3


def _before(tools: list[str], a: str, b: str) -> bool:
    return a in tools and b in tools and tools.index(a) < tools.index(b)


def _inv(tools: list[str], level) -> bool:  # search 발동 ⟺ level 중/하
    return ("search_postings" in tools) == (level in ("중", "하"))


def _cases(url: str, img_url: str, bad_url: str):
    # (name, query, profile_present, check(tools, level) -> bool | None(관찰))
    return [
        ("S1 추천", "내 이력서로 갈 만한 공고 추천해줘", True,
         lambda t, l: "search_postings" in t and "analyze_gap" not in t),
        ("S2 공고정리", f"이 공고 내용이 뭔지 알려줘 {url}", False,
         lambda t, l: "load_posting" in t and "analyze_gap" not in t),
        ("S3 갭분석", f"내 이력서로 이 공고 붙을까? {url}", True,
         lambda t, l: _before(t, "load_posting", "analyze_gap") and _inv(t, l)),
        ("S4 직군검색", "데이터 엔지니어 공고 찾아줘", True,
         lambda t, l: "search_postings" in t),
        ("S5 일상", "나 요즘 취준 힘들어", True,
         lambda t, l: t == []),
        ("S6 무관", "오늘 날씨 어때?", True,
         lambda t, l: t == []),
        ("E1 없는URL", f"이 공고 갈 수 있어? {bad_url}", True,
         lambda t, l: "load_posting" in t),
        ("E2 이미지공고", f"이 공고 갈 수 있어? {img_url}", True,
         lambda t, l: "load_posting" in t and "analyze_gap" in t),
        ("E3 애매(관찰)", "이 회사 괜찮아?", True, None),
    ]


def main() -> int:
    from agent import run_agent
    from preprocess import parse_resume
    from tools import search_postings

    n = _runs_arg()
    print(f"이력서 파싱 중... (케이스별 {n}회 실행)")
    profile = parse_resume("sample_data/이력서_이서현_프론트엔드.docx")
    url = search_postings("백엔드").postings[0].url
    img_url = "https://www.jobkorea.co.kr/Recruit/GI_Read/49637618"     # need_ocr=O
    bad_url = "https://www.jobkorea.co.kr/Recruit/GI_Read/00000000"     # 없음
    cases = _cases(url, img_url, bad_url)

    print(f"\n=== Agent Eval — {len(cases)} 케이스 × {n}회 ===")
    deviated = 0
    for name, query, has_prof, check in cases:
        prof = profile if has_prof else None
        runs = []
        for _ in range(n):
            r = run_agent(query, prof)
            runs.append((r.meta.tools_called, r.meta.level))

        if check is None:  # 관찰 케이스 — 정답 없이 분포만
            dist = Counter(tuple(t) for t, _ in runs)
            print(f"\n[{name}] 관찰 — tools 분포:")
            for pat, c in dist.items():
                print(f"    {c}/{n}  {list(pat)}")
            continue

        passed = sum(1 for t, l in runs if check(t, l))
        mark = "✅" if passed == n else ("⚠️" if passed else "❌")
        print(f"\n[{name}] {mark} 일관성 {passed}/{n}")
        for i, (t, l) in enumerate(runs, 1):  # 실행별 원문 기록(증거)
            print(f"    run{i} {'ok  ' if check(t, l) else '이탈'}: tools={t} level={l}")
        if passed < n:
            deviated += 1

    print(f"\n=== 판정 케이스 중 이탈 {deviated}건 "
          f"({'전부 일관' if deviated == 0 else '위 덤프 확인'}) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
