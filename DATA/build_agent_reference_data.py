"""통합 채용공고와 취업 후기를 로드맵 에이전트용 참조 JSON으로 내보낸다."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


JOB_POSTINGS = Path("exports/all_job_postings.json")
REVIEWS = Path("exports/review_articles.json")
OUT = Path("exports/agent_reference_data.json")


def load(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"필수 데이터 파일이 없습니다: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    job_postings = load(JOB_POSTINGS)
    reviews = load(REVIEWS)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "job_postings": job_postings,
        "acceptance_reviews": reviews,
        "counts": {
            "job_postings": len(job_postings),
            "acceptance_reviews": len(reviews),
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[agent_reference] status=completed job_postings={len(job_postings)} "
        f"acceptance_reviews={len(reviews)} json={OUT}",
        flush=True,
    )


if __name__ == "__main__":
    main()
