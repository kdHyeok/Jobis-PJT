"""로컬 공고 DB — URL 정확 조회(load_posting) + 키워드 검색(search_postings).

Agent_Test(프로토타입 1.0.0)의 도구 계약을 그대로 이식했다. 데이터·백엔드가 갈리는
구조도 동일하다:

  · load_posting  = 데이터팀 DB 의 **키 조회** 자리. 지금은 크롤링 샘플 JSON 인덱스.
    실제 DB 가 오면 이 파일의 몸통(_load_index / load_posting)만 바꾼다 — 호출부 불변.
  · search_postings = RAG 팀 **의미 검색** 자리(입출력 계약: RAG_입출력_명세서 3필드
    match_reason). 지금은 naive 키워드 매칭 Mock. RAG 가 오면 rag.py 의 어댑터
    provider 분기만 실구현으로 바꾼다 — 이 Mock 은 그때도 폴백으로 남는다.

데이터 위치: 환경변수 POSTINGS_DB_DIR (기본: <repo>/sample_data/"db내 공고파일").
데이터팀 파일이 오면 그 디렉토리에 JSON 을 넣거나 POSTINGS_DB_DIR 로 가리키면
재시작만으로 동작한다. 파일 형식: [{source, posting_id, company, title, url,
employment_type, experience, education, location, posted_date, deadline,
detail_text, need_ocr?, ...}] (jobkorea·wanted 크롤링 합본과 동일 스키마).

LLM 을 쓰지 않는 결정적 도구다. 실패는 예외 대신 None/빈 목록으로 낸다.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "sample_data" / "db내 공고파일"

_lock = threading.Lock()
_INDEX: dict[str, dict] | None = None      # url → 공고 원본
_SEARCHABLE: list[dict] | None = None      # 본문 있는 공고만 (검색 후보)

TOP_K = 5


def _db_dir() -> Path:
    return Path(os.getenv("POSTINGS_DB_DIR") or _DEFAULT_DIR)


def _load() -> tuple[dict[str, dict], list[dict]]:
    global _INDEX, _SEARCHABLE
    with _lock:
        if _INDEX is not None:
            return _INDEX, _SEARCHABLE or []
        index: dict[str, dict] = {}
        searchable: list[dict] = []
        directory = _db_dir()
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                try:
                    postings = json.loads(path.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    continue      # 깨진 파일은 건너뛴다 — DB 일부 손상이 전체를 죽이면 안 된다
                for p in postings if isinstance(postings, list) else []:
                    url = str(p.get("url") or "").strip()
                    if url:
                        index[url] = p
                    # need_ocr=="O"(이미지 공고, 본문 미추출)는 검색 후보에서 제외
                    if str(p.get("need_ocr") or "X") != "O" and str(p.get("detail_text") or "").strip():
                        searchable.append(p)
        _INDEX, _SEARCHABLE = index, searchable
        return index, searchable


def reset_cache() -> None:
    """데이터 파일 교체 후 재적재용 (테스트·핫스왑)."""

    global _INDEX, _SEARCHABLE
    with _lock:
        _INDEX = _SEARCHABLE = None


def db_available() -> bool:
    """공고 DB 가 하나라도 적재됐는지 — rag 어댑터의 자동 선택 근거."""

    index, _ = _load()
    return bool(index)


def load_posting(url: str) -> dict | None:
    """공고 URL 정확 일치 조회. 없으면 None (NOT_FOUND 의미 — 예외 없음)."""

    if not (url or "").strip():
        return None
    return _load()[0].get(url.strip())


# 첫 숫자를 잡는다. '경력 3-8년' 은 3~8년이므로 **하한 3** 이 요구 최소 연차다.
# ('\d+\s*년' 로 잡으면 년에 붙은 8 을 집어 3년차를 걸러내는 과도 필터가 된다.)
_YEARS_RE = re.compile(r"(\d+)")


def experience_floor_years(text: str | None) -> float | None:
    """연차 표기 → **요구 최소 연차**. 신입 지원 가능이면 0.0, 못 읽으면 None.

    크롤링 데이터의 실제 표기(공고 1743건에 93종)를 그대로 따른다:

      '신입' · '경력무관' · '신입·경력' · '신입-경력 3년'  → 0.0   (신입 가능)
      '경력 3년' · '경력 3-8년'                          → 3.0   (범위는 **하한**)
      '경력'  (연차 미표기)                               → 1.0   (경력자만 뽑는다는 뜻)
      빈 값 · 숫자도 키워드도 없음                          → None  (모르면 거르지 않는다)

    사용자가 말한 경력 수준("신입", "경력 3년")에도 같은 규칙을 쓴다 — 공고 쪽은 "요구 최소",
    사용자 쪽은 "보유"라는 의미 차이만 있고 표기 해석은 동일하다.

    LLM 을 쓰지 않는 결정적 파서다.
    """

    s = (text or "").strip()
    if not s:
        return None
    # '경력무관' 은 '경력' 도 포함하므로 무관·신입을 먼저 본다.
    if "무관" in s or "신입" in s:
        return 0.0
    if "경력" in s:
        m = _YEARS_RE.search(s)
        return float(m.group(1)) if m else 1.0
    m = _YEARS_RE.search(s)
    return float(m.group(1)) if m else None


# 제목에 박힌 명시 연차: '경력7년이상', '경력 3년 이상'. **'경력' 이 숫자에 붙어 있을 때만**
# 인정한다 — '창립 20년', '2026년 신입' 같은 무관한 숫자를 연차로 오인하지 않기 위해서다.
_TITLE_YEARS_RE = re.compile(r"경력\s*(\d+)\s*년")


def posting_floor_years(experience: str | None, title: str | None = None) -> float | None:
    """공고의 요구 최소 연차. 정형 표기(experience)를 기준으로 하고, 그것이 연차를 안 담을 때만
    제목의 명시 연차로 보강한다.

    크롤링 데이터에는 `experience` 가 연차 없이 '경력' 인데 제목에는 '경력7년이상' 이라고
    적힌 공고가 있다(실측: 5년차에게 7년 요구 공고가 추천됐다). 제목은 **올릴 때만** 쓴다 —
    '신입' 표기를 제목 때문에 뒤집지는 않는다.
    """

    floor = experience_floor_years(experience)
    if floor is None or floor > 0:
        m = _TITLE_YEARS_RE.search(title or "")
        if m:
            from_title = float(m.group(1))
            if floor is None or from_title > floor:
                return from_title
    return floor


# 경력자에게 허용하는 초과 연차. 3년차에게 4년 요구 공고는 보여줄 만하다(도전 가능).
# 신입(0년)에는 적용하지 않는다 — 아래 fits_experience 참고.
OVER_YEARS_TOLERANCE = 1.0


def fits_experience(posting_floor: float | None, user_years: float | None) -> bool:
    """공고 요구 연차가 사용자 연차에 맞는지. 어느 쪽이든 모르면 통과(거르지 않는다).

    `job_recommend`(공고 추천)와 `find_alternatives`(대안 공고)가 **같은 규칙**을 써야 한다 —
    한쪽에만 있으면 같은 사용자에게 한 답변에서는 걸러지고 다른 답변에서는 8년 요구 공고가
    나간다(D115). 그래서 판정을 이 한 곳에 둔다.
    """

    if posting_floor is None or user_years is None:
        return True
    if user_years <= 0:
        # 신입에게는 "신입 지원 가능" 공고만. 연차 미표기 '경력' 공고(데이터의 최다 유형)도
        # 경력자 채용이므로 제외한다 — 이게 신입에게 8년 요구 공고가 가던 원인이었다.
        return posting_floor <= 0
    return posting_floor <= user_years + OVER_YEARS_TOLERANCE


def posting_to_text(posting: dict) -> str:
    """공고 원본 dict → 파서(extract)가 먹는 평문. 필드는 있는 것만 싣는다."""

    head = [
        f"회사: {posting.get('company')}" if posting.get("company") else "",
        f"공고명: {posting.get('title')}" if posting.get("title") else "",
        f"경력: {posting.get('experience')}" if posting.get("experience") else "",
        f"학력: {posting.get('education')}" if posting.get("education") else "",
        f"고용형태: {posting.get('employment_type')}" if posting.get("employment_type") else "",
        f"근무지: {posting.get('location')}" if posting.get("location") else "",
        f"마감: {posting.get('deadline')}" if posting.get("deadline") else "",
    ]
    body = str(posting.get("detail_text") or "").strip()
    return "\n".join([line for line in head if line] + ["", body]).strip()


def search_postings(terms: list[str], *, top_k: int = TOP_K) -> list[dict]:
    """용어 목록으로 공고를 찾는다(키워드 매칭 Mock). 계약: RAG_입출력_명세서.

    반환: 원본 공고 필드 + score(0~1) + match_reason{matched_skills, matched_keywords,
    matched_fields}. 0건이면 빈 목록. 실제 RAG(의미 검색)로 교체돼도 이 형태는 불변이다.
    """

    terms = [t.strip() for t in terms if t and t.strip()]
    if not terms:
        return []
    _, searchable = _load()
    scored: list[tuple[float, dict]] = []
    for p in searchable:
        title = str(p.get("title") or "")
        hay = f"{title} {p.get('detail_text', '')}".lower()
        matched = [t for t in terms if t.lower() in hay]
        if not matched:
            continue
        in_title = [t for t in matched if t.lower() in title.lower()]
        score = round(len(matched) / len(terms), 3)
        scored.append((score + 0.001 * len(in_title), {
            **p,
            "score": score,
            "match_reason": {
                "matched_skills": matched,
                "matched_keywords": in_title,
                "matched_fields": ["title" if in_title else "detail_text"],
            },
        }))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:top_k]]
