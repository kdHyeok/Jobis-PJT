"""스모크 실행 진입점 — Agent를 한 번 돌려본다 (AGENTS §8).

사용: python run.py   (필요: .env의 GMS_KEY, sample_data)
시나리오3(이력서+공고 갭분석) 흐름을 실제로 돌려 로그·최종 응답을 출력한다.
"""
import logging

from agent import run_agent
from preprocess import parse_resume
from tools import search_postings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    profile = parse_resume("sample_data/이력서_이서현_프론트엔드.docx")
    url = search_postings("백엔드").postings[0].url  # 프론트 이력서엔 갭 큰 공고
    query = f"내 이력서로 이 공고에 지원하면 붙을 수 있을까? {url}"

    print(f"\n[질의] {query}\n")
    result = run_agent(query, profile)

    print("\n=== 최종 응답 ===")
    print(result.reply)
    print("\n[meta]", result.meta.model_dump())


if __name__ == "__main__":
    main()
