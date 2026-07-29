"""소스 로더 + 경량 정규화.

입력: 5개 크롤링 소스 통일 스키마 JSON (all_job_postings.json 형태).
정책:
  - need_ocr=O 또는 detail_text 빈 공고는 인덱싱 제외 (OCR 도입 후 편입)
  - 지저분한 실데이터 파싱은 전부 여기에 격리 — 청킹/임베딩은 Posting만 신뢰
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .role_taxonomy import classify as classify_role
from .schema import Posting
from .whitelist import extract_tech

_EXP_RANGE_RE = re.compile(r"(\d+)\s*[-~]\s*(\d+)\s*년")   # "3-8년" -> 하한 3, 상한 8
_EXP_MIN_RE = re.compile(r"최소\s*(\d+)\s*년")
_EXP_ANY_RE = re.compile(r"(\d+)\s*년")
# 시/도 + (선택) 시군구 1개까지: "경기 성남시 분당구" -> ("경기", "성남시")
_REGION_RE = re.compile(
    r"(서울|경기|인천|부산|대구|광주|대전|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"(?:특별시|광역시|특별자치시|특별자치도|도)?\s*([가-힣]+[시군구])?"
)
# 시/도 접두어 없이 구 이름만 적힌 주소("마포구 양화로 125")를 구제.
# 다른 시/도와 겹치는 이름(중구·강서구 등)은 제외해 오귀속을 막는다.
_SEOUL_ONLY_GU = (
    "종로구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 "
    "서대문구 마포구 양천구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구"
).split()
_GU_RE = re.compile(r"([가-힣]+구)")


def parse_exp_range(raw: str) -> tuple[int | None, int | None, bool]:
    """경력 문자열 -> (exp_min, exp_max, 의심 여부). 신입=(0,None), 무관/파싱불가=(None,None).

    "3-8년" 같은 범위 표현은 _EXP_ANY_RE만 쓰면 "년" 바로 앞 숫자(상한 8)를
    exp_min으로 잘못 집는다 — 범위 정규식을 먼저 시도해 하한/상한을 분리한다.
    """
    if not raw:
        return None, None, False
    if "신입" in raw:
        return 0, None, False
    if "무관" in raw:
        return None, None, False
    m = _EXP_RANGE_RE.search(raw)
    if m:
        return int(m.group(1)), int(m.group(2)), False
    m = _EXP_MIN_RE.search(raw) or _EXP_ANY_RE.search(raw)
    if m:
        return int(m.group(1)), None, False
    # 크롤러 오정렬 쓰레기("] JAVA..." 등) — None + 의심 표시
    return None, None, "경력" not in raw


def parse_regions(raw: str) -> list[str]:
    """근무지 문자열 -> 계층 확장된 지역 리스트.

    공고는 근무지를 여러 개 갖는 일이 흔하므로(37% 이상) 전부 보존한다.
    또 "서울" 질의가 "서울 강남구" 공고를 놓치지 않도록 시도 단위도 함께 넣는다
    (인덱스 측 확장 — 기술 별칭 병기와 같은 원리).
        "서울 송파구, 경기 성남시" -> ["서울", "서울 송파구", "경기", "경기 성남시"]
    """
    out: list[str] = []

    def add(item: str) -> None:
        if item not in out:
            out.append(item)

    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        m = _REGION_RE.search(part)
        if m:
            add(m.group(1))
            if m.group(2):
                add(f"{m.group(1)} {m.group(2)}")
            continue
        # 시/도 없이 구만 있는 주소 — 서울 고유 구 이름일 때만 서울로 귀속
        gu = _GU_RE.search(part)
        if gu and gu.group(1) in _SEOUL_ONLY_GU:
            add("서울")
            add(f"서울 {gu.group(1)}")
    return out


def to_posting(rec: dict) -> Posting:
    exp_min, exp_max, exp_suspect = parse_exp_range(rec.get("experience") or "")
    regions = parse_regions(rec.get("location") or "")
    title = rec.get("title", "")
    detail_text = rec.get("detail_text") or ""
    text_for_tech = f"{title}\n{detail_text}"
    tech = extract_tech(text_for_tech)
    return Posting(
        posting_id=str(rec.get("posting_id", "")),
        source=rec.get("source", ""),
        company=rec.get("company", ""),
        title=title,
        url=rec.get("url", ""),
        employment_type=rec.get("employment_type", ""),
        experience_raw=rec.get("experience") or "",
        exp_min=exp_min,
        exp_max=exp_max,
        education=rec.get("education", ""),
        location_raw=rec.get("location") or "",
        regions=regions,
        deadline=rec.get("deadline") or "",
        detail_text=detail_text,
        tech=tech,
        role_category=classify_role(title, detail_text, tech),
        collected_at=rec.get("collected_at", ""),
        needs_review=exp_suspect,
    )


def load_postings(path: str | Path) -> tuple[list[Posting], dict]:
    """JSON 로드 -> (인덱싱 대상 Posting 리스트, 제외 통계)."""
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    postings, skipped_ocr, skipped_empty = [], 0, 0
    for rec in records:
        if rec.get("need_ocr") == "O":
            skipped_ocr += 1
            continue
        if not (rec.get("detail_text") or "").strip():
            skipped_empty += 1
            continue
        postings.append(to_posting(rec))
    stats = {
        "total": len(records),
        "indexed": len(postings),
        "skipped_ocr": skipped_ocr,
        "skipped_empty_text": skipped_empty,
        "needs_review": sum(1 for p in postings if p.needs_review),
    }
    return postings, stats
