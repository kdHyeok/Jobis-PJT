# -*- coding: utf-8 -*-
"""1.0.1 강건화 '측정 먼저' 관찰 harness (analyze_gap 개선 前/後 A/B용).

6개 프로필 × (S1 추천 / S3 갭분석) — 라우팅(run_agent) + 판단근거(툴 직접호출).
- 라우팅: run_agent → tools_called / level / auto_search 진입
- 판단근거: search_postings·analyze_gap 직접 호출 → score·matched/missing·rationale

실행: .venv/Scripts/python.exe tests/observe_gap_baseline.py
※ 라이브 GMS 호출. analyze_gap 리팩터 후 재실행해 W1~W4 개선 여부를 같은 잣대로 확인.
"""
import sys, os, re, json

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)

from preprocess.resume_parser import parse_resume
import tools as T
from agent.graph import run_agent
from schemas import GapResult, Posting

DB_DIR = os.path.join(BASE, "sample_data", "db내 공고파일")

# (표시명, 이력서경로, 필드라벨, 공고title 정규식, 노림)
PROFILES = [
    ("정민준/백엔드",     "sample_data/합성이력서/이력서_정민준_백엔드.docx",       "백엔드", r"백엔드|back.?end|서버|java|spring", "상"),
    ("김도윤/부트캠프BE", "sample_data/합성이력서/이력서_김도윤_백엔드부트캠프.docx", "백엔드", r"백엔드|back.?end|서버|java|spring", "중"),
    ("한유진/데이터",     "sample_data/합성이력서/이력서_한유진_데이터사이언스.docx", "데이터", r"데이터|data\b|사이언|scientist|분석가|analyst|머신러닝|\bml\b", "중"),
    ("오세훈/안드로이드", "sample_data/합성이력서/이력서_오세훈_안드로이드.docx",   "모바일", r"안드로이드|android|모바일|mobile", "중/하"),
    ("박지호/정보보안",   "sample_data/합성이력서/이력서_박지호_정보보안.docx",     "보안",   r"보안|security|정보보호", "하/희소"),
    ("이서현/프론트",     "sample_data/이력서_이서현_프론트엔드.docx",             "프론트", r"프론트|front|react|vue", "(baseline)"),
]


def load_all_postings():
    out = []
    for f in ("jobkorea_job_postings.json", "wanted_job_postings.json"):
        out += json.load(open(os.path.join(DB_DIR, f), encoding="utf-8"))
    return out


def pick_posting(postings, title_re):
    """같은 필드 + need_ocr=X + detail_text + (가능하면 신입/무관). 결정적 first-match."""
    cand = [p for p in postings
            if p.get("need_ocr") == "X"
            and (p.get("detail_text") or "").strip()
            and re.search(title_re, p.get("title") or "", re.I)]
    junior = [p for p in cand if re.search(r"신입|무관", p.get("experience") or "")]
    if junior:
        return junior[0], "신입/무관"
    if cand:
        return cand[0], "경력요건 완화(신입공고 없음)"
    return None, "매칭 공고 없음"


def fmt_list(lst, n=6):
    lst = list(lst or [])
    s = ", ".join(str(x) for x in lst[:n])
    if len(lst) > n:
        s += f" …(+{len(lst)-n})"
    return "[" + s + "]"


def main():
    ALL = load_all_postings()
    print(f"공고 총 {len(ALL)}건 로드\n" + "=" * 78)
    summary = []

    for name, path, field, title_re, aim in PROFILES:
        print(f"\n[{name}]  노림={aim}")
        try:
            profile = parse_resume(path)
        except Exception as e:
            print(f"  ✗ 파싱 실패: {e}")
            continue

        posting_raw, pick_note = pick_posting(ALL, title_re)
        if posting_raw is None:
            print(f"  ✗ {field} 필드 공고 없음 — S3 건너뜀")
            url = None
        else:
            url = posting_raw.get("url")
            print(f"  대상공고: {posting_raw.get('title','')[:46]}  | 경력:{posting_raw.get('experience')} ({pick_note})")

        # S1 추천: 라우팅 + 근거
        r1 = run_agent("제 이력서를 기반으로 잘 맞는 채용공고를 추천해 주세요.", profile)
        s1 = T.search_postings(profile)
        s1top = " / ".join(
            f"{p.company}|{str(p.title)[:22]} score={p.score} {fmt_list(p.match_reason.matched_skills, 4)}"
            for p in s1.postings[:3]
        ) or "0건"
        print(f"  S1 추천  라우팅 tools={r1.meta.tools_called}")
        print(f"           근거 top3: {s1top}")

        # S3 갭분석: 라우팅 + 근거
        agent_level = None
        auto = None
        gap = None
        if url:
            r3 = run_agent(f"다음 공고가 제 이력/역량과 얼마나 맞는지 분석해 주세요: {url}", profile)
            tc = r3.meta.tools_called
            agent_level = r3.meta.level
            auto = ("search_postings" in tc[tc.index("analyze_gap") + 1:]) if "analyze_gap" in tc else False
            print(f"  S3 갭분석 라우팅 tools={tc} level={agent_level} auto_search진입={'O' if auto else 'X'}")
            posting = T.load_posting(url)
            if isinstance(posting, Posting):
                gap = T.analyze_gap(profile, posting)
                if isinstance(gap, GapResult):
                    print(f"           근거 score={gap.score:.2f} level={gap.level}")
                    print(f"             충족(필수) {fmt_list(gap.matched_required)}")
                    print(f"             부족(필수) {fmt_list(gap.missing_required)}")
                    print(f"             우대충족   {fmt_list(gap.matched_preferred)}")
                    print(f"             판정불가   {fmt_list(gap.uncertain)}")
                    print(f"             rationale: {gap.rationale}")
                else:
                    print(f"           근거 분석실패: {getattr(gap,'detail',gap)}")
            else:
                print(f"           공고 재조회 실패: {getattr(posting,'detail',posting)}")

        summary.append((name, aim, agent_level,
                        (gap.level if isinstance(gap, GapResult) else None),
                        auto))
        print("-" * 78)

    print("\n" + "=" * 78 + "\n요약 (노림 vs 관찰)\n" + "=" * 78)
    print(f"{'프로필':16s} {'노림':7s} {'agent level':11s} {'직접 level':9s} {'auto_search':11s}")
    for name, aim, al, dl, au in summary:
        print(f"{name:16s} {aim:7s} {str(al):11s} {str(dl):9s} {str(au):11s}")


if __name__ == "__main__":
    main()
