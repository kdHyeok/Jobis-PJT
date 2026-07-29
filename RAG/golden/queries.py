"""골든셋 질의 — 종합 평가용.

v3(2026-07-28): 프로덕션 형태 — 되묻기 완료 후의 완성형 쿼리.
실제 서비스에서는 사용자가 "AWS 인프라 엔지니어"라고 입력하면
챗봇이 지역·경력 등을 되물어 모든 축이 채워진 상태로 검색이 호출된다.
평가 쿼리도 이 완성형을 반영해야 프로덕션 성능을 정확히 측정한다.

모든 쿼리는 tech + region + exp 3축이 text에 포함된다.
카테고리는 쿼리의 주요 테스트 초점을 나타낸다.

카테고리별 층화:
  [기존 — 완성형으로 보강]
  tech_focus(7) region_focus(6) exp_focus(5) colloquial_region(6)
  tech_alias(6) combo_balanced(8) combo_dense(5) sparse_relax(5) freeform(2) = 50
  [엣지케이스]
  parser_trap(3) multi_tech(3) boundary_exp(3) negative_signal(3) low_resource_role(3) = 15
"""

QUERIES = [
    # --- tech_focus: 기술 축이 검색 결과를 좌우 (지역·경력은 보통값) ---
    {"id": "q01", "text": "서울 3년차 Java 백엔드 개발자", "category": "tech_focus"},
    {"id": "q02", "text": "경기 신입 React 프론트엔드 채용", "category": "tech_focus"},
    {"id": "q03", "text": "서울 5년차 Python 데이터 엔지니어", "category": "tech_focus"},
    {"id": "q04", "text": "서울 경력무관 TypeScript 쓰는 회사", "category": "tech_focus"},
    {"id": "q05", "text": "서울 5년차 AWS 인프라 엔지니어", "category": "tech_focus"},
    {"id": "q06", "text": "경기 3년차 PostgreSQL 다루는 백엔드", "category": "tech_focus"},
    {"id": "q07", "text": "서울 경력무관 LLM 활용하는 AI 엔지니어", "category": "tech_focus"},

    # --- region_focus: 지역 필터가 핵심 (기술·경력은 보통값) ---
    {"id": "q08", "text": "서울 3년차 Python 개발자 채용", "category": "region_focus"},
    {"id": "q09", "text": "경기도 신입 Java 개발자", "category": "region_focus"},
    {"id": "q10", "text": "대전 3년차 React 소프트웨어 엔지니어", "category": "region_focus"},
    {"id": "q11", "text": "부산 신입 Spring 개발자 채용", "category": "region_focus"},
    {"id": "q12", "text": "인천 경력무관 프론트엔드 React 개발자", "category": "region_focus"},
    {"id": "q13", "text": "광주 신입 Node.js 백엔드 개발자", "category": "region_focus"},

    # --- exp_focus: 경력 조건이 후보풀을 좌우 ---
    {"id": "q14", "text": "서울 신입 Python 개발자 채용", "category": "exp_focus"},
    {"id": "q15", "text": "서울 경력 3년 이상 Java 개발자", "category": "exp_focus"},
    {"id": "q16", "text": "경기 경력 5년차 Spring 백엔드", "category": "exp_focus"},
    {"id": "q17", "text": "서울 경력무관 React 개발자 채용", "category": "exp_focus"},
    {"id": "q18", "text": "서울 시니어 Java 개발자", "category": "exp_focus"},

    # --- colloquial_region: 구어체 지명 파싱 테스트 ---
    {"id": "q19", "text": "강남에서 3년차 Java 백엔드 개발자", "category": "colloquial_region"},
    {"id": "q20", "text": "판교 신입 React 프론트엔드 개발자", "category": "colloquial_region"},
    {"id": "q21", "text": "분당 경력무관 Python 개발자 채용", "category": "colloquial_region"},
    {"id": "q22", "text": "여의도 3년차 금융 IT Java 개발자", "category": "colloquial_region"},
    {"id": "q23", "text": "성남 신입 Spring 백엔드", "category": "colloquial_region"},
    {"id": "q24", "text": "역삼 경력무관 React 스타트업 채용", "category": "colloquial_region"},

    # --- tech_alias: 한글/구어체 기술명 파싱 테스트 ---
    {"id": "q25", "text": "서울 3년차 스프링부트 하는 회사", "category": "tech_alias"},
    {"id": "q26", "text": "서울 신입 리액트 개발자", "category": "tech_alias"},
    {"id": "q27", "text": "서울 5년차 쿠버네티스 다루는 데브옵스", "category": "tech_alias"},
    {"id": "q28", "text": "경기 3년차 도커 쓰는 백엔드", "category": "tech_alias"},
    {"id": "q29", "text": "서울 신입 노드js 백엔드 개발자", "category": "tech_alias"},
    {"id": "q30", "text": "서울 경력무관 파이썬 데이터 분석가", "category": "tech_alias"},

    # --- combo_balanced: 세 축 균형 조합 ---
    {"id": "q31", "text": "서울에서 3년차 Java Spring 백엔드", "category": "combo_balanced"},
    {"id": "q32", "text": "경기 신입 React 프론트엔드", "category": "combo_balanced"},
    {"id": "q33", "text": "서울 3년차 Python 개발자", "category": "combo_balanced"},
    {"id": "q34", "text": "서울 신입 TypeScript 프론트엔드 개발자", "category": "combo_balanced"},
    {"id": "q35", "text": "서울 5년 이상 AWS 인프라 엔지니어", "category": "combo_balanced"},
    {"id": "q36", "text": "서울 경력무관 LLM 엔지니어", "category": "combo_balanced"},
    {"id": "q37", "text": "서울 신입 Spring 백엔드 개발자", "category": "combo_balanced"},
    {"id": "q38", "text": "경기 5년차 Docker 데브옵스", "category": "combo_balanced"},

    # --- combo_dense: 조건 많은 고밀도 조합 ---
    {"id": "q39", "text": "서울 강남 스프링부트 3년차 백엔드", "category": "combo_dense"},
    {"id": "q40", "text": "경기 판교 신입 프론트엔드 리액트", "category": "combo_dense"},
    {"id": "q41", "text": "부산 신입 Java 백엔드 개발자", "category": "combo_dense"},
    {"id": "q42", "text": "대전 경력무관 Python 데이터 엔지니어", "category": "combo_dense"},
    {"id": "q43", "text": "서울 시니어 쿠버네티스 데브옵스", "category": "combo_dense"},

    # --- sparse_relax: 희소 조합 — 완화 경로 테스트 ---
    {"id": "q44", "text": "대구에서 5년차 Kubernetes 다루는 시니어 개발자", "category": "sparse_relax"},
    {"id": "q45", "text": "제주에서 신입 React 프론트엔드 개발자", "category": "sparse_relax"},
    {"id": "q46", "text": "울산 3년차 Python 데이터 엔지니어", "category": "sparse_relax"},
    {"id": "q47", "text": "충북 신입 Java 백엔드 개발자", "category": "sparse_relax"},
    {"id": "q48", "text": "경남 3년차 Go 시스템 프로그래머", "category": "sparse_relax"},

    # --- freeform: 자유형 자연어 (되묻기 후에도 구조화 어려운 케이스) ---
    {"id": "q49", "text": "서울 경력무관 요즘 뜨는 AI 스타트업 Python 개발자 자리 있을까", "category": "freeform"},
    {"id": "q50", "text": "서울 3년차 재택 가능한 Java 백엔드 개발자 자리 찾아요", "category": "freeform"},

    # ===== 엣지케이스 (q51~q65) =====

    # --- parser_trap: 파서 오작동 유도 ---
    {"id": "q51", "text": "서울 3년차 설립 10년 이상 된 회사에서 Java 백엔드 개발자", "category": "parser_trap"},
    {"id": "q52", "text": "서울 Vue 3년 경험 프론트엔드", "category": "parser_trap"},
    {"id": "q53", "text": "서울 golang 10년차 서버 개발자", "category": "parser_trap"},

    # --- multi_tech: 기술 2개+ 교집합 ---
    {"id": "q54", "text": "서울 3년차 React TypeScript 프론트엔드 개발자", "category": "multi_tech"},
    {"id": "q55", "text": "서울 신입 Python FastAPI 백엔드", "category": "multi_tech"},
    {"id": "q56", "text": "서울 5년차 Docker Kubernetes 다루는 인프라 엔지니어", "category": "multi_tech"},

    # --- boundary_exp: 연차 경계값 ---
    {"id": "q57", "text": "서울 경력 1년차 Spring 백엔드 개발자", "category": "boundary_exp"},
    {"id": "q58", "text": "서울 경력 10년 이상 Java 시니어 아키텍트", "category": "boundary_exp"},
    {"id": "q59", "text": "서울 2년차 Python 주니어 개발자", "category": "boundary_exp"},

    # --- negative_signal: 파서 구조밖 표현 ---
    {"id": "q60", "text": "서울 3년차 Java 쓰는데 Spring 말고 다른 프레임워크 쓰는 곳", "category": "negative_signal"},
    {"id": "q61", "text": "서울 3년차 핀테크 쪽 Java 개발자 자리 괜찮은 데 있을까", "category": "negative_signal"},
    {"id": "q62", "text": "서울 신입 계약직 말고 정규직 Python 백엔드 개발자", "category": "negative_signal"},

    # --- low_resource_role: 희소 직군 ---
    {"id": "q63", "text": "서울 3년차 Python QA 엔지니어 테스트 자동화", "category": "low_resource_role"},
    {"id": "q64", "text": "서울 3년차 AWS SRE 엔지니어 채용", "category": "low_resource_role"},
    {"id": "q65", "text": "서울 3년차 Python 보안 엔지니어 취약점 분석", "category": "low_resource_role"},
]

assert len(QUERIES) == 65
assert len({q["id"] for q in QUERIES}) == 65
