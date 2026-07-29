"""공용 데이터 스키마.

Posting: 크롤링 원본(5개 소스 통일 스키마)을 경량 정규화한 결과.
Chunk: 청킹 산출물 — 프리픽스 포함 텍스트가 그대로 임베딩 입력이 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Posting:
    posting_id: str                  # 소스 내에서만 유일 — 소스 간에는 충돌한다
    source: str                      # 고용24 | 사람인 | 원티드 | 인크루트 | 잡코리아
    company: str
    title: str
    url: str
    employment_type: str
    experience_raw: str              # 원문 보존
    exp_min: int | None              # 신입=0, 파싱 실패=None(무관 취급)
    education: str
    location_raw: str
    deadline: str
    detail_text: str
    # 계층 확장된 근무지 전량: ["서울", "서울 강남구", "경기", "경기 성남시"]
    # 다중 근무지 공고가 많고, 시도 단위 질의도 걸려야 하므로 배열로 둔다.
    regions: list[str] = field(default_factory=list)
    tech: list[str] = field(default_factory=list)   # 화이트리스트 표준명
    role_category: str = ""          # 12종 enum. 룰 분류 실패 시 "" (미분류)
    collected_at: str = ""
    needs_review: bool = False       # 정규화 단계에서 의심 표시
    exp_max: int | None = None       # 범위 공고("3-8년")의 상한. 상한 없음/개방=None

    @property
    def region_display(self) -> str:
        """프리픽스용 표기. 시도 단위 확장분은 빼고 가장 구체적인 지역만 보여준다."""
        specific = [r for r in self.regions if " " in r]
        shown = specific or self.regions
        if not shown:
            return "지역 미상"
        return ", ".join(shown[:3]) + (f" 외 {len(shown) - 3}곳" if len(shown) > 3 else "")

    @property
    def uid(self) -> str:
        """전역 유일키. 동일 공고가 여러 사이트에 올라오면 posting_id가 겹치므로
        (source, posting_id) 조합을 써야 한쪽이 덮어써지지 않는다.
        크로스사이트 중복 병합은 이와 별개의 단계에서 다룬다."""
        return f"{self.source}:{self.posting_id}"


@dataclass
class Chunk:
    chunk_id: str
    posting_uid: str                 # Posting.uid 참조
    part: str                        # full | split
    text: str                        # 프리픽스 포함 — 이 텍스트를 그대로 임베딩
    tokens: int
    forced_split: bool = False       # 항목 경계가 아닌 하드컷 발생 (방어 코드)
    needs_review: bool = False
