# 테스트 로그 — 사용자 수동 대화 테스트 (2026-07-27)

- **테스트일**: 2026-07-27
- **대상 프로그램**: `chat.py` — 대화형 스모크 (사용자가 직접 질의)
- **실행 명령**: `.venv\Scripts\python.exe chat.py`
- **커밋**: task 10 이후 상태
- **테스터**: 사용자 (직접 경우의 수별 테스트)

## 결과·관찰 (S1~S4)
| 케이스 | 입력 | tools_called | level | 판정 |
|---|---|---|---|---|
| S1 추천 | "내 이력서로 갈 만한 공고 추천" | `search_postings` | None | ✅ 3건 + URL |
| S2 공고정리 | "이 공고 내용/요건 알려줘 {url}" | `load_posting` | None | ✅ 담당업무·자격요건까지 요약 |
| **S3 갭분석** | "이력서로 이 공고 붙을까? {엠플랜잇 url}" | `load_posting, analyze_gap` | **상** | ✅ **상 → search 없음** |
| S4 직군검색 | "데이터 엔지니어 공고 찾아줘" | `search_postings` | None | ✅ 데이터엔지니어 3건 + URL |

### ★ 핵심 발견 — 성공기준 3 런타임 검증
- S3에서 **level=상**(엠플랜잇 프론트엔지니어 공고 × 프론트 이력서) → `tools=['load_posting', 'analyze_gap']`, **search_postings 없음**.
- 지금까지 상 케이스가 안 나와 **조건엣지 코드로만 보장**하던 "상 → 대체직군 검색 안 함(기준3)"이 **실제 실행에서 처음 확인**됨.
- → 이로써 **성공기준 5개 전부 런타임 시연 완료**(1·2·4·5는 task 08·10, 3은 이 세션).

## 대화 로그 (raw)
```
완료 — 스킬 28개.  (참고용 공고 URL: https://www.jobkorea.co.kr/Recruit/GI_Read/49637342)

나> 내 이력서로 갈 만한 공고 추천해줘
[d22f8262][step 1] node=agent tool_calls=['search_postings']
[d22f8262] node=tools tool=search_postings → 공고 3건: 아이비티에스㈜ | 금융,공공,일반기업 운영개발[SM,SI] | .../49564982 ...
[d22f8262][step 2] node=agent tool_calls=[]
에이전트> 다음은 당신의 이력서를 기반으로 추천하는 공고입니다:
1. [아이비티에스㈜ | 금융,공공,일반기업 운영개발[SM,SI]](.../49564982) - 매칭: JavaScript(ES6+), TypeScript, HTML5
2. [㈜앱메이드 | JAVA 개발-금융,공공,일반기업 운영개발[SM,SI]](.../49283237) - 매칭: JavaScript, TypeScript, HTML5
3. [엠플랜잇 | 기술연구소 프론트엔지니어/ IT&AI서비스 개발PM](.../49591474) - 매칭: JavaScript, TypeScript, HTML5
[meta] tools=['search_postings'] · level=None

나> 이 공고 내용/요건 알려줘 https://www.jobkorea.co.kr/Recruit/GI_Read/49591474
[fbea729e][step 1] node=agent tool_calls=['load_posting']
[fbea729e] node=tools tool=load_posting → 공고 조회 OK — 엠플랜잇 | 기술연구소 프론트엔지니어/ IT&AI서비스 개발PM 채용
[fbea729e][step 2] node=agent tool_calls=[]
에이전트> 공고 제목: [엠플랜잇] 기술연구소 프론트엔지니어/ IT&AI서비스 개발PM 채용
- 경력: 경력(3-5년 이상) / 지역: 서울 강남구 언주로93길 21 / 마감: 2026-08-31
### 담당 업무: React/Next.js 기반 웹 애플리케이션 개발, 반응형·UI 컴포넌트, 디자인 시스템,
  REST API 연동, 백오피스/대시보드, 협업, 유지보수·성능개선
### 자격 요건: React, Next.js 관련 경험 ...
[meta] tools=['load_posting'] · level=None

나> 이력서로 이 공고 붙을까? https://www.jobkorea.co.kr/Recruit/GI_Read/49591474
[7ea977b4][step 1] node=agent tool_calls=['load_posting', 'analyze_gap']
[7ea977b4] node=tools tool=load_posting → 공고 조회 OK — 엠플랜잇 | 기술연구소 프론트엔지니어...
[7ea977b4] node=tools tool=analyze_gap → 갭분석 결과 level=상 | 충족 ['React, Next.js 실무 개발 경험', 'TypeScript 활용 경험', '상태관리(Zustand)...']
[7ea977b4][step 2] node=agent tool_calls=[]        ← search 없음 (상)
에이전트> 갭 분석 결과, 지원 가능성이 **상**으로 평가되었습니다. 대부분의 기술 요건은 충족하지만,
  '서비스 기획/PM 경력 5~8년 이상'이 부족한 것으로 나타났습니다. ...
[meta] tools=['load_posting', 'analyze_gap'] · level=상

나> 데이터 엔지니어 공고 찾아줘
[bf56bf94][step 1] node=agent tool_calls=['search_postings']
[bf56bf94] node=tools tool=search_postings → 공고 3건: ㈜미리디 | [미리디] 데이터 엔지니어 | .../49500715 (score ...) ...
[bf56bf94][step 2] node=agent tool_calls=[]
에이전트> 데이터 엔지니어 관련 공고:
1. ㈜미리디 | [미리디] 데이터 엔지니어 | .../49500715
2. 래브라도랩스 | 데이터 엔지니어(파이썬 개발자) | wanted.co.kr/wd/363969
3. 에이엑스 | AI 에이전트 개발자(백엔드+데이터) | wanted.co.kr/wd/347793
[meta] tools=['search_postings'] · level=None
```

## 피드백·후기
- **프로토타입으로서 성공적**: S1~S4 + (이전) 실패/엣지 케이스 모두 정상. 사용자 평가 "당장은 성공적으로 작동".
- **S2 공고정리**가 담당업무·자격요건까지 풍부 — 본문 발췌 수정 효과.
- **S3 상 케이스**로 기준3(상→검색X) 런타임 검증 — 5기준 전부 실증 완료.
- **잔여 약점(스코프 내)**: S1 추천이 SI/Java 위주(mock 검색 정밀도↓). 단 그 목록 3위 엠플랜잇(프론트)을 S3로 분석하니 analyze_gap은 정확히 **상** → **얕은 검색(mock)은 랭킹 부정확, 깊은 분석(analyze_gap)은 신뢰**. 검색 정밀도는 실제 RAG가 해결.
