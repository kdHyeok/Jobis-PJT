"""대화형 스모크 — 직접 질의를 넣어 Agent 흐름을 눈으로 본다.

사용: python chat.py   (이력서 자동 파싱 후, 질의를 입력)
예)
  내 이력서로 이 공고 붙을까? https://www.wanted.co.kr/wd/376543
  프론트엔드 공고 추천해줘
  데이터 엔지니어 공고 찾아줘
  나 요즘 너무 힘들어
  오늘 서울 날씨 어때?
종료: 빈 줄 또는 exit
"""
import logging

from agent import run_agent
from preprocess import parse_resume
from tools import search_postings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    print("이력서 파싱 중...")
    profile = parse_resume("sample_data/이력서_이서현_프론트엔드.docx")
    sample = search_postings("백엔드").postings[0].url
    print(f"완료 — 스킬 {len(profile.skills)}개.  (참고용 공고 URL: {sample})")
    print("질의를 입력하세요. 종료는 빈 줄/exit.\n")

    while True:
        try:
            q = input("나> ").strip()
        except EOFError:
            break
        if not q or q.lower() in ("exit", "quit", "종료"):
            break
        print("─── Agent 흐름 ───")
        r = run_agent(q, profile)
        print(f"\n에이전트> {r.reply}")
        print(f"[meta] tools={r.meta.tools_called} · level={r.meta.level} · run_id={r.meta.run_id}\n")


if __name__ == "__main__":
    main()
