# RAG 공고 검색 — 입출력 명세서

> **이 문서의 목적**
> RAG 담당 개발자가 이 문서 하나만 보고, **어떤 데이터를 어떤 형태로 입력받아 → 어떤 데이터를 어떤 형태로 AI Agent 쪽에 돌려주는** 검색 컴포넌트(툴/시스템)를 만들 수 있도록 정의합니다.

---

## 1. 시스템 내 위치

```
[AI Agent] ──(입력: 직업명 or 이력서)──▶ [RAG 공고 검색] ──(출력: 관련 공고들)──▶ [AI Agent]
                                              │
                                        (공고 DB / 벡터스토어)
```

- AI Agent가 "이 조건으로 유사한 공고 찾아줘"라고 **RAG를 호출**합니다.
- RAG는 공고 DB에서 **관련도 높은 공고들을 찾아** 정해진 형태로 돌려줍니다.
- **검색 방식(임베딩·키워드·필드 가중치 등)은 전적으로 RAG 재량**입니다. 이 문서는 **입력/출력 계약(interface)만** 규정합니다.

---

## 2. 입력 (Input)

입력은 **아래 두 형태 중 하나**로 들어옵니다. RAG는 두 경우를 모두 처리해야 합니다.

### 입력 A — 직업명 (문자열)

- 타입: `string`
- 의미: 특정 직군명으로 관련 공고를 찾음
- 예시:

```
"데이터 엔지니어"
```

```
"백엔드 개발자"
```

### 입력 B — 이력서 (파싱된 profile JSON)

- 타입: `object` (JSON)
- 의미: 이력서 파싱 결과 전체를 넘김. 이 사람과 유사한/적합한 공고를 찾음
- **스키마 (`_UserProfileRead`)**:

| 필드 | 설명 | 구조 |
|------|------|------|
| `education` | 학력 | `[{ id, school, major, degree, status, period }]` |
| `experiences` | 재직이력 | `[{ id, company, role, employmentType, period, summary }]` |
| `projects` | 프로젝트 | `[{ id, title, projectType, period, teamSize, role, summary, techStack[], achievements[] }]` |
| `skills` | 기술 | `[{ name, level }]` |
| `certifications` | 자격증 | `[{ id, name, status, acquiredDate }]` |
| `languages` | 어학 | `[{ id, name, testName, score, testDate, proficiency }]` |
| `bootcamp` | 부트캠프 | `[{ id, name, organization, track, period, summary }]` |
| `awards` | 수상 | `[{ id, title, organization, date, description }]` |
| `evidenceMap` | 근거문장 (메타) | `[{ evidenceId, source, text }]` |
| `uncertainties` | 불확실사항 (메타) | `[string]` |

- **없는 항목은 빈 배열 `[]`** 로 옵니다. (예: 자격증이 없으면 `"certifications": []`)
- **검색 신호로 어느 필드를 쓸지는 RAG 재량**입니다. (참고: `skills`, `projects.techStack`, `experiences.role` 이 매칭 신호가 강함)
- `evidenceMap`, `uncertainties` 는 **파서 내부 메타데이터**이므로 검색 신호로 쓰지 않아도 됩니다.

- **입력 B 예시** (프론트엔드 개발자):

```json
{
  "education": [
    { "id": "edu-1", "school": "OO대학교", "major": "컴퓨터공학", "degree": "학사", "status": "졸업", "period": "2018.03 ~ 2022.02" }
  ],
  "experiences": [
    { "id": "exp-1", "company": "OO스타트업", "role": "프론트엔드 개발자", "employmentType": "정규직", "period": "2022.03 ~ 2024.06", "summary": "React 기반 웹 서비스 프론트엔드 개발 및 유지보수" }
  ],
  "projects": [
    { "id": "prj-1", "title": "커머스 웹 리뉴얼", "projectType": "실무", "period": "2023.01 ~ 2023.08", "teamSize": 5, "role": "프론트엔드 리드",
      "summary": "React + TypeScript 기반 커머스 프론트엔드 전면 개편", "techStack": ["React", "TypeScript", "Next.js", "Redux"],
      "achievements": ["초기 로딩 속도 40% 개선", "컴포넌트 재사용 구조 도입"] }
  ],
  "skills": [
    { "name": "React", "level": "상" },
    { "name": "TypeScript", "level": "상" },
    { "name": "JavaScript", "level": "상" },
    { "name": "Next.js", "level": "중" }
  ],
  "certifications": [],
  "languages": [
    { "id": "lang-1", "name": "영어", "testName": "TOEIC", "score": "870", "testDate": "2023.05", "proficiency": "업무 가능" }
  ],
  "bootcamp": [],
  "awards": [],
  "evidenceMap": [
    { "evidenceId": "ev-1", "source": "exp-1", "text": "React 기반 웹 서비스 프론트엔드 개발 및 유지보수를 담당했습니다." }
  ],
  "uncertainties": []
}
```

---

## 3. 출력 (Output)

### 핵심 규칙

> **원본 공고 필드는 절대 변경하지 말고 그대로 두고, `score` 와 `match_reason` 두 필드만 각 공고에 추가합니다.**
> 결과는 여러 개이므로 **`postings` 배열**로 담아 반환합니다. (관련도 높은 순 정렬, 기본 `top_k = 3`)

### 출력 구조

```json
{
  "postings": [
    { /* 원본 공고 JSON + score + match_reason */ },
    { /* ... */ }
  ]
}
```

> 참고: 검색 성공/실패를 감싸는 `ok` / `error` 봉투는 **이후 단계(실패 처리)에서 추가 예정**이며, 현재 프로토타입 단계에서는 위 `postings` 배열 반환에 집중합니다.

### 출력 예시 (공고 2건)

```json
{
  "postings": [
    {
      "source": "잡코리아",
      "posting_id": "49638148",
      "company": "㈜무투스랩",
      "title": "대기업 모빌리티 플랫폼 프로젝트 SW 개발자 채용",
      "url": "https://www.jobkorea.co.kr/Recruit/GI_Read/49638148",
      "employment_type": "정규직",
      "experience": "경력",
      "education": "학력무관",
      "location": "서울 강남구 언주로85길 23-6 (역삼동) 4층",
      "posted_date": "2026-07-23",
      "deadline": "2026-08-22T23:59",
      "detail_text": "㈜무투스랩\n... (원본 전문 그대로, 절대 수정/요약 금지) ...",
      "image_urls": [],
      "need_ocr": "X",
      "collected_at": "2026-07-23T04:56:22+00:00",

      "score": 0.82,
      "match_reason": {
        "matched_skills": ["React", "TypeScript", "Next.js"],
        "matched_keywords": ["프론트엔드", "웹 애플리케이션"],
        "matched_fields": ["skills", "projects.techStack"]
      }
    },
    {
      "source": "원티드",
      "posting_id": "376431",
      "company": "인투씨엔에스",
      "title": "백엔드 개발자 (Java/Spring Boot, 3-5년)",
      "url": "https://www.wanted.co.kr/wd/376431",
      "employment_type": null,
      "experience": "경력 3-5년",
      "education": null,
      "location": "경기도 용인시 수지구 ...",
      "posted_date": null,
      "deadline": "상시채용",
      "detail_text": "주요업무• Java, Spring Boot 기반 API ... (원본 전문 그대로)",
      "image_urls": [],
      "need_ocr": "X",
      "collected_at": "2026-07-23T06:44:47+00:00",

      "score": 0.61,
      "match_reason": {
        "matched_skills": ["JavaScript"],
        "matched_keywords": ["개발자"],
        "matched_fields": ["skills"]
      }
    }
  ]
}
```

### 결과가 0건일 때

검색은 정상 수행됐지만 맞는 공고가 없으면 **빈 배열**을 반환합니다.

```json
{ "postings": [] }
```

---

## 4. 필드 설명

### 원본 공고 필드 (공고 DB에 저장된 그대로, **변경 금지**)

| 필드 | 의미 |
|------|------|
| `source` | 공고 출처 사이트 (예: 잡코리아, 원티드) |
| `posting_id` | 공고 고유 ID |
| `company` | 회사명 |
| `title` | 공고 제목 |
| `url` | 공고 원본 링크 |
| `employment_type` | 고용형태 (정규직 등), 없으면 `null` |
| `experience` | 경력 요건 |
| `education` | 학력 요건, 없으면 `null` |
| `location` | 근무지 |
| `posted_date` | 게시일, 없으면 `null` |
| `deadline` | 마감일 |
| `detail_text` | **공고 본문 전문** (필수/우대 요건 포함) — 검색·매칭의 핵심 소스 |
| `image_urls` | 본문이 이미지일 때의 링크 |
| `need_ocr` | 본문이 이미지인지 (`X`=텍스트 있음 / `O`=이미지, 본문 없음) |
| `collected_at` | 데이터 수집(크롤링) 시각 |

### RAG가 추가하는 필드 (2개만)

| 필드 | 타입 | 의미 |
|------|------|------|
| `score` | `float` | 관련도 점수 (높을수록 위, 정렬 기준) |
| `match_reason` | `object` | 왜 이 공고가 매칭됐는지 (디버깅/관측용) |
| `match_reason.matched_skills` | `string[]` | 입력과 겹친 스킬 |
| `match_reason.matched_keywords` | `string[]` | 겹친 키워드 |
| `match_reason.matched_fields` | `string[]` | 매칭에 기여한 입력 필드 (예: `skills`, `projects.techStack`) |

---

## 5. 요약 (한눈에)

| 구분 | 내용 |
|------|------|
| **입력** | 직업명(`string`) **또는** 이력서 profile(`JSON`) 중 하나 |
| **출력** | `{ "postings": [ 원본 공고 JSON + score + match_reason, ... ] }` |
| **정렬** | `score` 내림차순 |
| **개수** | 기본 `top_k = 3` |
| **0건** | `{ "postings": [] }` |
| **절대 규칙** | 원본 공고 필드는 **변경 없이 그대로**, `score`·`match_reason`만 추가 |
| **검색 방식** | RAG 재량 (이 문서 범위 밖) |

> 한 줄 요약: **"직업명 또는 이력서를 받아 → 공고 DB에서 관련도 순으로 찾아 → 원본 공고 JSON에 `score`·`match_reason`만 얹어 `postings` 배열로 돌려준다."**
