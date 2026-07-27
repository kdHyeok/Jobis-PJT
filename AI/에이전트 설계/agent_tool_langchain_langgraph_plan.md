# 잡퀘스트 멀티에이전트 / 툴 / LangChain-LangGraph 설계 정리

## 1. 설계 방향 요약

이 프로젝트는 단일 LLM 응답형 서비스가 아니라, 채용공고 구조화, 사용자 이력 구조화, 갭 분석, 준비 로드맵 생성, 대체 경로 추천, 결과 검증까지 이어지는 다단계 취업 준비 에이전트로 설계한다.[cite:21] 회의 문서에서도 핵심 흐름을 `목표 채용공고 입력 → 사용자 이력 및 경험 선택 → 공고 요구사항 구조화 → 사용자 경험과 비교 → 부족 역량 및 강점 분석 → 준비 우선순위 결정 → 기간별 준비 로드맵 생성 → 유사 직무·대체 공고 제안`으로 정의하고 있다.[cite:21]

따라서 전체 시스템은 **오케스트레이터 + 역할 기반 워커 에이전트** 구조로 잡고, 오케스트레이션과 상태 관리는 LangGraph로, 각 에이전트 내부의 체인과 툴 연결은 LangChain으로 설계하는 것이 가장 자연스럽다.[cite:21][cite:31][cite:33]

## 2. LangGraph와 LangChain을 어디에 쓰는가

LangChain은 LLM, 문서 로더, 파서, 벡터 검색, structured output 등을 선형 또는 소규모 분기형 체인으로 연결할 때 적합하다.[cite:31][cite:56] 반면 LangGraph는 여러 에이전트를 노드 단위로 연결하고, 분기, 루프, 상태 저장, 재시도 같은 오케스트레이션을 구현할 때 적합하다.[cite:31][cite:33]

이 프로젝트에 적용하면 다음처럼 정리된다.[cite:21][cite:33]

- **LangGraph**: Orchestrator, 에이전트 간 호출 순서, 상태 관리, 추가 질문 분기, 실패 시 재시도 루프 담당.[cite:31][cite:33]
- **LangChain**: Job Posting Parser, User Profile Builder, Gap Analyzer, Roadmap Planner 같은 각 에이전트 내부 로직 담당.[cite:31][cite:56]

즉, 한 줄로 말하면 **위에서 전체 흐름을 관리하는 것은 LangGraph, 각 에이전트 안에서 툴을 엮어 실제 작업을 처리하는 것은 LangChain**이다.[cite:31][cite:33]

## 3. 멀티에이전트 전체 구조

문서 기준으로 추천하는 에이전트 구조는 다음과 같다.[cite:21]

- Orchestrator
- Job Posting Parser
- User Profile Builder
- Gap Analyzer
- Roadmap Planner
- Alternative Path Finder
- Result Verifier

이 구조는 문서의 기본 흐름인 `사용자 요청 → 채용공고 구조화 → 사용자 이력 조회 → 정보 충분성 판단 → 공고 요구사항 추출 → 내부 DB 및 RAG 조회 → 부족 정보 웹 검색 → 사용자와 공고 간 갭 분석 → 준비 로드맵 생성 → 대체 경로 생성 → 결과 검증 → JSON 출력`과 직접 대응된다.[cite:21]

## 4. 에이전트별 역할과 툴

| 에이전트 | 핵심 역할 | 주요 입력 | 주요 출력 | 주요 툴 |
|---|---|---|---|---|
| Orchestrator | 전체 흐름 제어, 분기 판단, 재시도 관리 | user request, userId, jobPostingInput, selectedExperienceIds, 기간/시간 정보[cite:21] | 최종 analysis package, followUpQuestions[cite:21] | `workflow_router`, `input_validator`, `question_generator`, `retry_manager`, `result_assembler`[cite:21] |
| Job Posting Parser | 공고 원문을 requirement 구조로 변환 | URL, 공고 원문 텍스트, 파일 업로드 데이터[cite:21] | required/preferred requirements, tech stack, role, domain tags[cite:21] | `job_posting_ingest`, `job_posting_text_extractor`, `job_requirement_parser`, `job_schema_normalizer`, `job_parsing_fallback`[cite:21] |
| User Profile Builder | 사용자 이력/프로젝트/기술을 evidence 단위로 구조화 | user profile DB, selectedExperienceIds, resume/portfolio text[cite:21] | normalizedUserProfile, evidenceMap, clarificationQuestions[cite:21] | `user_profile_fetcher`, `resume_text_extractor`, `experience_selector`, `profile_structurer`, `clarification_generator`, `profile_merge_tool`[cite:21] |
| Gap Analyzer | 공고 요구사항과 사용자 경험 비교, 강점/부족 판정 | normalizedJobPosting, normalizedUserProfile, company context[cite:21] | strengths, gaps, requirement status, score basis(optional)[cite:21] | `requirement_matcher`, `evidence_mapper`, `gap_scorer`, `fit_reasoner`, `company_context_fetcher`, `rag_insight_fetcher`, `priority_ranker`[cite:21] |
| Roadmap Planner | 부족 역량을 기간별 행동 계획으로 변환 | gaps, availableHoursPerWeek, preparationPeriodWeeks[cite:21] | roadmap JSON, tasks, doneCriteria, priority[cite:21] | `roadmap_generator`, `task_prioritizer`, `timeline_allocator`, `completion_criteria_builder`, `calendar_json_formatter`, `constraint_reflector`[cite:21] |
| Alternative Path Finder | 유사 직무·낮은 요구수준 공고·우회 경로 추천 | current job posting, gaps, user profile[cite:21] | alternativeJobs, recommendation reasons[cite:21] | `similar_job_search`, `alternative_role_mapper`, `lower_barrier_filter`, `recommendation_reasoner`, `company_cluster_search`[cite:21] |
| Result Verifier | 결과 검수, 금지 표현·누락 필드·정합성 검사 | combined analysis result[cite:21] | validatedResult, warnings, retry signal[cite:21] | `output_schema_validator`, `policy_checker`, `evidence_checker`, `consistency_checker`, `rewrite_softener`, `warning_generator`[cite:21] |

## 5. 공통 기반 툴

여러 에이전트가 공통으로 쓰는 기반 툴은 별도 레이어로 두는 것이 좋다.[cite:21]

| 공통 툴 | 용도 | 연결 에이전트 |
|---|---|---|
| `structured_db_query` | 내부 정형 DB 조회 | 대부분의 에이전트[cite:21] |
| `vector_search` | 벡터 DB / RAG 검색 | Gap Analyzer, Alternative Path Finder 등[cite:21] |
| `web_search` | 자체 검색 툴, 부족 정보 보완 | Gap Analyzer, Alternative Path Finder[cite:21] |
| `document_text_extract` | PDF/Word/한글/텍스트 추출 | Job Posting Parser, User Profile Builder[cite:21] |
| `json_schema_validate` | 출력 JSON 검증 | Result Verifier, Orchestrator[cite:21] |
| `tool_logger` | 툴 호출 기록 및 상태 로그 | Orchestrator 중심[cite:21] |
| `failure_handler` | 재시도, fallback, 사용자 알림 | Orchestrator, Result Verifier[cite:21] |

## 6. 데이터 조회 우선순위

모든 에이전트는 동일한 데이터 접근 우선순위를 따라야 한다.[cite:21]

1. 내부 정형 DB[cite:21]
2. 벡터 DB 또는 RAG[cite:21]
3. 자체 웹 검색 툴[cite:21]
4. 외부 LLM 검색 기능[cite:21]

이 원칙을 지키면 비용, 재현성, 신뢰성을 동시에 관리하기 쉽다.[cite:18][cite:21]

## 7. MVP 우선 구현 에이전트

문서 기준 핵심 가치가 `특정 공고 기준 갭 분석 + 실행 가능한 로드맵 + 대체 경로 제안`이므로, MVP에서는 다음 에이전트를 우선 구현하면 된다.[cite:21]

- Job Posting Parser[cite:21]
- User Profile Builder[cite:21]
- Gap Analyzer[cite:21]
- Roadmap Planner[cite:21]
- Result Verifier(가능하면 포함)[cite:21]

Alternative Path Finder는 2차 우선순위로 두는 것이 현실적이다.[cite:21]

## 8. Job Posting Parser의 LangChain 설계

### 8.1 목표

Job Posting Parser는 URL, 원문 텍스트, 파일 업로드 형태의 채용공고를 받아서, 필수/우대/기술요건/직무 맥락이 분리된 구조화 JSON으로 변환하는 역할을 맡는다.[cite:21] 이 에이전트는 사용자의 적합도 판단이나 로드맵 설계를 수행하지 않고, 오직 공고를 비교 가능한 requirement 구조로 바꾸는 데만 집중한다.[cite:21]

### 8.2 목표 출력 예시

```json
{
  "jobTitle": "",
  "companyName": "",
  "roleCategory": "",
  "seniority": "",
  "requiredRequirements": [],
  "preferredRequirements": [],
  "techStack": [],
  "domainKeywords": [],
  "rawChunks": [],
  "uncertainties": []
}
```

### 8.3 체인 단계

1. **Input Normalize Chain**: sourceType을 `url | text | file`로 판별하고 공통 입력 포맷으로 정리한다.[cite:21][cite:75]
2. **Text Extract Chain**: URL이면 본문 추출, 파일이면 텍스트 추출, raw text면 그대로 통과시킨다.[cite:21][cite:69]
3. **Requirement Parse Chain**: 공고 본문에서 직무명, 필수/우대, 기술 스택, 연차, 도메인 키워드를 structured output으로 추출한다.[cite:21][cite:56]
4. **Schema Normalize Chain**: requirement 문장 표준화, 중복 제거, taxonomy 매핑을 수행한다.[cite:21]
5. **Output Validate Chain**: 필수 필드와 스키마를 검증하고 warnings를 생성한다.[cite:21][cite:55]

### 8.4 LangChain 구성 요소

| 단계 | LangChain 요소 | 설명 |
|---|---|---|
| 입력 정규화 | `RunnableLambda` | sourceType 판별, 공통 포맷 변환[cite:75] |
| 분기 처리 | `RunnableBranch` | url/file/text 분기[cite:69][cite:76] |
| 텍스트 추출 | tool + runnable | 외부 함수 또는 서비스 호출[cite:69] |
| requirement 파싱 | `ChatPromptTemplate + with_structured_output` | 구조화 JSON 출력[cite:54][cite:56] |
| 정규화 | `RunnableLambda` | taxonomy mapping, 중복 제거[cite:75] |
| 검증 | Pydantic/schema validator | 필수 필드/타입 검증[cite:55][cite:56] |

### 8.5 체인 흐름

```text
jobPostingInput
→ normalize_input
→ branch_by_source_type
    ├─ url_fetch
    ├─ file_extract
    └─ raw_text_pass
→ parse_requirements_with_structured_output
→ normalize_schema
→ validate_output
→ normalizedJobPosting
```

## 9. User Profile Builder의 LangChain 설계

### 9.1 목표

User Profile Builder는 사용자의 이력서, 포트폴리오, 선택한 경험 데이터를 읽고, 공고와 비교 가능한 evidence 중심 프로필로 변환하는 역할을 맡는다.[cite:21] 문서에서도 사용자 이력은 AI가 공통 스키마에 맞게 구조화하고, 부족하거나 모호한 정보가 있으면 추가 질문을 생성하도록 설계되어 있다.[cite:21]

### 9.2 목표 출력 예시

```json
{
  "education": [],
  "experiences": [],
  "projects": [],
  "skills": [],
  "certifications": [],
  "languages": [],
  "bootcamp": [],
  "awards": [],
  "portfolioLinks": [],
  "evidenceMap": [],
  "clarificationQuestions": [],
  "uncertainties": []
}
```

### 9.3 체인 단계

1. **Input Normalize Chain**: userId, selectedExperienceIds, 업로드 파일 존재 여부를 정리한다.[cite:21][cite:75]
2. **Source Gather Chain**: 사용자 DB 조회, 선택 경험 필터링, 이력서/포트폴리오 텍스트 추출을 병렬로 수행한다.[cite:21][cite:72]
3. **Profile Parse Chain**: 학력, 경력, 프로젝트, 기술, 자격증, 어학 등을 공통 스키마로 구조화한다.[cite:21][cite:56]
4. **Evidence Enrich Chain**: 프로젝트의 문제-조치-성과 구조를 강화하고 evidenceMap을 생성한다.[cite:21]
5. **Clarification Generate Chain**: 모호하거나 부족한 부분에 대한 추가 질문을 3~5개 수준으로 생성한다.[cite:21]
6. **Output Validate Chain**: 필수 상위 필드, evidenceMap, clarificationQuestions 등을 검증한다.[cite:21][cite:56]

### 9.4 LangChain 구성 요소

| 단계 | LangChain 요소 | 설명 |
|---|---|---|
| 입력 정규화 | `RunnableLambda` | 입력 형식 정리[cite:75] |
| 소스 수집 | `RunnableParallel` | DB 조회와 파일 추출 병렬 처리[cite:72] |
| 선택 경험 필터 | `RunnableLambda` | selectedExperienceIds 기준 필터링[cite:75] |
| 프로필 구조화 | `ChatPromptTemplate + with_structured_output` | 사용자 프로필 JSON 반환[cite:56][cite:74] |
| evidence 강화 | `RunnableLambda` + 보조 LLM | 취업 근거 중심 재정리[cite:21][cite:74] |
| 질문 생성 | `with_structured_output` | clarificationQuestions 생성[cite:56] |
| 검증 | schema validator | 필드/정합성 점검[cite:56][cite:75] |

### 9.5 체인 흐름

```text
user profile input
→ normalize_input
→ gather_sources_parallel
    ├─ fetch_user_profile_db
    ├─ select_experiences
    ├─ extract_resume_text
    └─ extract_portfolio_text
→ parse_profile_with_structured_output
→ enrich_evidence
→ generate_clarification_questions
→ validate_output
→ normalizedUserProfile
```

## 10. Gap Analyzer의 LangChain 설계

### 10.1 목표

Gap Analyzer는 Job Posting Parser가 만든 `normalizedJobPosting`과 User Profile Builder가 만든 `normalizedUserProfile`을 입력받아, 공고의 각 요구사항이 사용자 경험(evidenceMap)으로 충족되는지를 판정하고 강점과 부족 역량을 도출하는 비교 엔진이다.[cite:21] 회의 문서의 분석 기준(필수 → 우대 → 사용자 경험 → 기업 정보 → 통계 → 후기 → 일반 정보)을 그대로 판정 근거 우선순위로 반영한다.[cite:21]

이 에이전트는 로드맵을 만들지 않고, 오직 `요구사항 ↔ 근거`의 매칭 상태와 판정 근거만 산출하는 데 집중한다.[cite:21]

### 10.2 목표 출력 예시

```json
{
  "requirementStatus": [
    {
      "requirementId": "",
      "type": "required | preferred",
      "text": "",
      "status": "met | partially_met | not_met | uncertain",
      "matchedEvidenceIds": [],
      "reason": "",
      "confidence": 0.0
    }
  ],
  "strengths": [],
  "gaps": [
    {
      "requirementId": "",
      "severity": "high | medium | low",
      "reason": "",
      "evidenceMissing": true
    }
  ],
  "scoreBasis": {
    "techSkill": null,
    "projectExperience": null,
    "certLanguage": null,
    "roleRelevance": null,
    "domainFit": null
  },
  "companyContext": [],
  "sources": [],
  "uncertainties": []
}
```

점수(`scoreBasis`)는 보조 지표이므로 산정 근거가 없으면 `null`로 두고, 점수만 단독으로 노출하지 않는다.[cite:21]

### 10.3 체인 단계

1. **Input Assemble Chain**: `normalizedJobPosting`, `normalizedUserProfile`, 기업 컨텍스트 요청 여부를 하나의 비교 입력으로 정리한다.[cite:21][cite:75]
2. **Requirement-Evidence Match Chain**: 각 requirement에 대해 evidenceMap에서 후보 근거를 검색·매칭한다. 1차로 taxonomy/키워드 기반 후보를 추리고, 2차로 LLM이 실제 충족 여부를 판정한다.[cite:21][cite:56]
3. **Context Enrich Chain**: 판정이 애매하거나 기업 맞춤 판단이 필요한 경우에만 `company_context_fetcher`와 `rag_insight_fetcher`로 보강한다. 데이터 조회 우선순위(내부 DB → 벡터/RAG → 웹 검색)를 지킨다.[cite:21]
4. **Gap Reasoning Chain**: 미충족·부분충족 항목을 근거 부족 유형과 함께 gap으로 구조화하고, 충족 항목은 강조 포인트(strength)로 정리한다.[cite:21]
5. **Priority Rank Chain**: 필수/우대 구분과 severity를 기준으로 부족 역량의 준비 우선순위를 매긴다. 이 순위가 Roadmap Planner의 입력이 된다.[cite:21]
6. **Output Validate Chain**: requirementStatus 누락, 금지된 단정 표현, 근거 없는 점수를 검증한다.[cite:21][cite:55]

### 10.4 LangChain 구성 요소

| 단계 | LangChain 요소 | 설명 |
|---|---|---|
| 입력 조립 | `RunnableLambda` | 공고·프로필·요청 병합[cite:75] |
| 후보 매칭 | `vector_search` tool + `RunnableLambda` | evidence 후보 검색·필터[cite:21] |
| 충족 판정 | `ChatPromptTemplate + with_structured_output` | requirementStatus 구조화 출력[cite:54][cite:56] |
| 컨텍스트 보강 | `RunnableBranch` + tool | 필요 시에만 기업/RAG 조회[cite:76] |
| 갭 추론 | `RunnableLambda` + 보조 LLM | gap/strength 재정리[cite:74] |
| 우선순위 | `RunnableLambda` | 필수/우대·severity 정렬[cite:75] |
| 검증 | schema/policy validator | 필드·표현·점수 근거 검증[cite:55][cite:56] |

### 10.5 체인 흐름

```text
normalizedJobPosting + normalizedUserProfile
→ assemble_comparison_input
→ match_requirements_to_evidence
    ├─ candidate_search (vector/keyword)
    └─ judge_fulfillment (structured output)
→ enrich_context_if_needed
    ├─ company_context_fetch
    └─ rag_insight_fetch
→ reason_gaps_and_strengths
→ rank_priority (required > preferred, severity)
→ validate_output
→ gapAnalysisResult
```

## 11. Roadmap Planner의 LangChain 설계

### 11.1 목표

Roadmap Planner는 Gap Analyzer가 우선순위를 매긴 부족 역량(gaps)을 입력받아, 사용자의 준비 기간(`preparationPeriodWeeks`)과 주당 가용 시간(`availableHoursPerWeek`) 제약 안에서 실행 가능한 기간별 준비 계획으로 변환한다.[cite:21] 결과는 프론트엔드가 타임라인·캘린더로 바로 렌더링할 수 있도록 JSON으로 반환한다.[cite:21]

### 11.2 목표 출력 예시

회의 문서의 최소 필드(제목·시작일·종료일·목표·세부 작업·완료 기준·우선순위·관련 공고 요구사항)를 그대로 스키마에 반영한다.[cite:21]

```json
{
  "roadmap": [
    {
      "title": "Spring Boot 프로젝트 완성",
      "startDate": "2026-08-01",
      "endDate": "2026-08-28",
      "goal": "배포 가능한 REST API 프로젝트 제작",
      "tasks": ["인증 기능 구현", "테스트 코드 작성", "성능 측정"],
      "doneCriteria": "배포 URL + 성능 측정 전후 수치 기록",
      "priority": "high",
      "relatedRequirementIds": [],
      "estimatedHours": 0
    }
  ],
  "totalWeeks": 16,
  "weeklyLoadHours": 20,
  "assumptions": [],
  "uncertainties": []
}
```

### 11.3 체인 단계

1. **Constraint Normalize Chain**: 기간·주당 시간·시작일을 정리하고, 총 가용 시간 예산을 계산한다.[cite:21][cite:75]
2. **Task Draft Chain**: 우선순위가 높은 gap부터 준비 과제(학습·구현·산출물)를 생성한다.[cite:21][cite:56]
3. **Timeline Allocate Chain**: 각 과제를 예상 소요 시간과 선후 관계에 따라 주차/구간에 배치하고, 주당 가용 시간을 초과하지 않도록 조정한다.[cite:21]
4. **Completion Criteria Chain**: 각 구간에 측정 가능한 완료 기준과 다음 단계 진입 조건을 붙인다.[cite:21]
5. **Calendar JSON Format Chain**: 프론트엔드 캘린더/타임라인 스키마에 맞춰 최종 JSON으로 포맷한다.[cite:21]
6. **Constraint Reflect / Validate Chain**: 총합 시간이 예산을 넘지 않는지, 날짜가 연속·정합적인지, 필수 필드가 채워졌는지 검증한다.[cite:21][cite:55]

### 11.4 LangChain 구성 요소

| 단계 | LangChain 요소 | 설명 |
|---|---|---|
| 제약 정규화 | `RunnableLambda` | 기간·시간 예산 계산[cite:75] |
| 과제 생성 | `ChatPromptTemplate + with_structured_output` | gap→task 구조화[cite:56] |
| 시간 배치 | `RunnableLambda` | 주차 배분·시간 초과 조정[cite:75] |
| 완료 기준 | `with_structured_output` | doneCriteria/진입 조건 생성[cite:56] |
| 캘린더 포맷 | `RunnableLambda` | 프론트 스키마 매핑[cite:75] |
| 검증 | schema validator | 시간 예산·날짜·필드 검증[cite:55][cite:56] |

### 11.5 체인 흐름

```text
rankedGaps + constraints(period, hours, startDate)
→ normalize_constraints (compute time budget)
→ draft_tasks_from_gaps
→ allocate_timeline (respect weekly hours)
→ attach_completion_criteria
→ format_calendar_json
→ reflect_constraints_and_validate
→ roadmapResult
```

## 12. Result Verifier의 검증 체인 설계

### 12.1 목표

Result Verifier는 앞선 에이전트들의 산출물을 합친 최종 결과 패키지를 검수하는 마지막 노드다.[cite:21] 스키마 정합성, 금지 표현, 근거 누락, 결과 간 모순을 검사하고, 문제가 있으면 완화(rewrite)하거나 오케스트레이터에 재시도 신호를 보낸다.[cite:21] 특히 회의에서 정한 **표현 원칙(합격/불합격 단정 금지, 권장 표현 사용)** 을 강제하는 게이트 역할을 한다.[cite:21]

### 12.2 목표 출력 예시

```json
{
  "validatedResult": {},
  "passed": true,
  "warnings": [],
  "violations": [
    { "type": "forbidden_expression | missing_field | inconsistent | no_evidence", "location": "", "detail": "" }
  ],
  "retrySignal": { "required": false, "targetAgent": null, "reason": "" }
}
```

### 12.3 검증 체인 단계

1. **Schema Validate Chain**: 최종 JSON이 출력 명세(강점·부족·요구사항·로드맵·대체공고·추가질문·출처)를 모두 갖췄는지 검사한다.[cite:21][cite:55]
2. **Policy Check Chain**: "지원 불가 / 합격 가능 / 반드시 / 무조건" 등 금지 표현을 탐지하고, 권장 표현으로 완화 후보를 만든다.[cite:21]
3. **Evidence Check Chain**: 강점·판정·점수에 대응하는 근거(evidenceId/sources)가 실제로 존재하는지 확인한다. 근거 없는 단정은 위반으로 처리한다.[cite:21]
4. **Consistency Check Chain**: gap과 roadmap이 대응되는지, requirementStatus와 strengths/gaps가 모순되지 않는지, 로드맵 기간이 입력 제약과 일치하는지 교차 검증한다.[cite:21]
5. **Rewrite Softener Chain**: 위반이 표현 수준이면 자동 완화하고, 구조적 결함이면 재시도 신호를 생성한다.[cite:21]
6. **Warning Generate Chain**: 치명적이지 않은 문제는 경고로 남겨 사용자·개발자에게 노출한다.[cite:21]

### 12.4 LangChain 구성 요소

| 단계 | LangChain 요소 | 설명 |
|---|---|---|
| 스키마 검증 | Pydantic / `json_schema_validate` | 필수 필드·타입 검증[cite:55][cite:56] |
| 정책 검사 | `RunnableLambda` + rule set | 금지 표현 탐지[cite:75] |
| 근거 검사 | `RunnableLambda` | evidenceId/sources 존재 확인[cite:75] |
| 정합성 검사 | `RunnableLambda` | 결과 간 교차 검증[cite:75] |
| 표현 완화 | `ChatPromptTemplate` | 권장 표현 재작성[cite:54] |
| 경고 생성 | `with_structured_output` | warnings/violations 구조화[cite:56] |

### 12.5 검증 흐름

```text
combinedResult
→ validate_schema
→ check_policy (forbidden expressions)
→ check_evidence (claims must have sources)
→ check_consistency (gap↔roadmap, status↔strength/gap, period)
→ if expression-level: soften_and_pass
   else: emit_retry_signal
→ generate_warnings
→ validatedResult (+ retrySignal)
```

## 13. LangGraph 오케스트레이터 전체 그래프 설계

### 13.1 역할

Orchestrator는 위 에이전트들을 노드로 연결하고, 상태(state)를 공유하며, 정보 충분성 판단에 따른 추가 질문 분기와 실패 시 재시도 루프를 관리하는 최상위 제어자다.[cite:21][cite:31][cite:33] LangChain 체인이 각 노드의 "내부 작업"이라면, LangGraph는 노드 사이의 "흐름·분기·루프·상태"를 담당한다.[cite:31][cite:33]

### 13.2 공유 상태(State) 스키마

모든 노드가 읽고 갱신하는 단일 상태 객체를 둔다. 회의의 입력/출력 명세를 그대로 반영한다.[cite:21]

```text
GraphState = {
  # 입력
  userId, jobPostingInput, selectedExperienceIds,
  preparationPeriodWeeks, availableHoursPerWeek,

  # 중간 산출물
  normalizedJobPosting,
  normalizedUserProfile,
  gapAnalysisResult,
  roadmapResult,
  alternativeJobs,

  # 제어/누적
  followUpQuestions,     # 사용자에게 되물을 질문
  sources,               # 근거·출처 누적
  toolLog,               # 툴 호출 로그
  retryCount,            # 노드별 재시도 횟수
  warnings,              # 검증 경고
  status                 # 진행 상태(프론트 표시용)
}
```

`status` 필드는 회의에서 요구한 진행 상태 시각화(공고 분석 중 → 경험 조회 중 → 로드맵 생성 중 …)를 프론트로 스트리밍하는 데 사용한다.[cite:21]

### 13.3 노드 구성

| 노드 | 담당 | 내부 구현 |
|---|---|---|
| `parse_job_posting` | 공고 구조화 | Job Posting Parser 체인(8장) |
| `build_user_profile` | 사용자 프로필 구조화 | User Profile Builder 체인(9장) |
| `check_sufficiency` | 정보 충분성 판단·분기 | Orchestrator 판단 체인 |
| `ask_user` | 추가 질문 생성 후 대기 | `question_generator` |
| `analyze_gap` | 갭 분석 | Gap Analyzer 체인(10장) |
| `plan_roadmap` | 로드맵 생성 | Roadmap Planner 체인(11장) |
| `find_alternatives` | 대체 경로(2차 우선순위) | Alternative Path Finder |
| `verify_result` | 최종 검증 | Result Verifier 체인(12장) |
| `assemble_output` | 최종 JSON 조립 | `result_assembler` |

### 13.4 엣지와 분기·루프

- **정보 충분성 분기**: `check_sufficiency`에서 정보가 부족하면 `ask_user`로 가서 followUpQuestions를 반환하고 그래프를 일시 중단(interrupt)한다. 사용자가 답하면 `build_user_profile`부터 재개한다.[cite:21][cite:33]
- **검증 재시도 루프**: `verify_result`가 `retrySignal.required = true`를 내면, `targetAgent`에 따라 해당 노드(`analyze_gap` 또는 `plan_roadmap`)로 되돌아간다. 단 `retryCount`가 상한(예: 2)을 넘으면 재시도를 멈추고 warnings와 함께 부분 결과를 반환한다.[cite:21]
- **실패 처리**: 각 툴 호출은 `failure_handler`로 감싸 재시도·fallback을 수행하고, 일정 횟수 이상 실패하면 사용자에게 알린다.[cite:21]
- **대체 경로 조건부 실행**: `find_alternatives`는 MVP에서 선택적으로 실행하며, 갭이 크거나 사용자가 요청한 경우에만 진입하도록 조건부 엣지로 둔다.[cite:21]

### 13.5 전체 그래프 흐름

```text
START
→ parse_job_posting
→ build_user_profile
→ check_sufficiency
    ├─ insufficient → ask_user → (interrupt / wait) → build_user_profile
    └─ sufficient → analyze_gap
→ analyze_gap
→ plan_roadmap
→ (optional) find_alternatives
→ verify_result
    ├─ retry(required, retryCount<max) → analyze_gap | plan_roadmap
    └─ pass → assemble_output
→ assemble_output
→ END
```

이 그래프는 회의 문서 9.2의 기본 흐름(`사용자 요청 → 공고 구조화 → 이력 조회 → 충분성 판단 → 갭 분석 → 로드맵 → 대체 경로 → 검증 → JSON 출력`)과 1:1로 대응된다.[cite:21]

### 13.6 MVP 구현 범위

MVP에서는 다음 경로를 우선 완성한다.[cite:21]

- 필수 노드: `parse_job_posting → build_user_profile → check_sufficiency → analyze_gap → plan_roadmap → verify_result → assemble_output`
- 재시도 루프와 추가 질문 분기는 **1회 수준**으로 단순하게 구현한다.
- `find_alternatives`는 2차 우선순위로 두고, 이후 조건부 엣지로 연결한다.[cite:21]

## 14. Alternative Path Finder의 LangChain 설계 (2차 우선순위)

### 14.1 목표

Alternative Path Finder는 Gap Analyzer 결과에서 부족 역량이 크거나 사용자가 요청했을 때, 목표 공고로 곧바로 진입하기 어려운 경우의 **대체 취업 경로**를 제안한다.[cite:21] 면담에서 강조된 "직접 경로 vs 대체 경로" 차별점을 구현하는 노드이며, 유사 직무·요구 연차가 낮은 공고·유사 기술 스택 기업·먼저 지원해볼 주니어 공고를 근거와 함께 추천한다.[cite:21]

이 노드는 MVP에서는 조건부(선택) 실행이며, 로드맵 이후 또는 병렬로 붙는다.[cite:21]

### 14.2 목표 출력 예시

```json
{
  "alternativeJobs": [
    {
      "type": "similar_role | lower_seniority | similar_stack | stepping_stone",
      "title": "",
      "companyName": "",
      "matchedStrengths": [],
      "reducedGaps": [],
      "reason": "",
      "sourceJobPostingId": null,
      "confidence": 0.0
    }
  ],
  "pathComparison": {
    "directPath": { "targetJob": "", "estimatedGapSize": "high | medium | low" },
    "alternativePaths": []
  },
  "sources": [],
  "uncertainties": []
}
```

`pathComparison`은 프론트에서 "직접 경로 vs 대체 경로"를 시각적으로 비교(면담 시연 포인트)하는 데 그대로 사용된다.[cite:21]

### 14.3 체인 단계

1. **Query Build Chain**: 현재 공고, gaps, 사용자 강점을 기반으로 대체 경로 탐색 쿼리를 만든다.[cite:21][cite:75]
2. **Candidate Search Chain**: 유사 직무/저연차/유사 스택 후보를 데이터 조회 우선순위(내부 DB → 벡터/RAG → 웹 검색)로 수집한다.[cite:21]
3. **Barrier Filter Chain**: 사용자 현재 역량으로 진입 장벽이 낮은 후보만 남기도록 필터링한다.[cite:21]
4. **Reason Chain**: 각 후보가 왜 대체 경로가 되는지(어떤 강점을 살리고 어떤 gap이 줄어드는지) 근거를 생성한다.[cite:21]
5. **Comparison Chain**: 직접 경로와 대체 경로를 비교 구조로 정리한다.[cite:21]
6. **Output Validate Chain**: 근거 없는 추천·단정 표현을 검증한다.[cite:21][cite:55]

### 14.4 LangChain 구성 요소

| 단계 | LangChain 요소 | 설명 |
|---|---|---|
| 쿼리 생성 | `RunnableLambda` | 탐색 쿼리 구성[cite:75] |
| 후보 검색 | `vector_search` + `web_search` tool | 유사 공고/직무 수집[cite:21] |
| 장벽 필터 | `RunnableLambda` | 저장벽 후보 선별[cite:75] |
| 추천 근거 | `ChatPromptTemplate + with_structured_output` | reason 구조화[cite:56] |
| 경로 비교 | `RunnableLambda` | direct/alternative 비교[cite:75] |
| 검증 | schema/policy validator | 근거·표현 검증[cite:55] |

### 14.5 체인 흐름

```text
gapAnalysisResult + normalizedUserProfile + currentJobPosting
→ build_alternative_query
→ search_candidates (db → vector/rag → web)
→ filter_low_barrier
→ reason_recommendations
→ build_path_comparison
→ validate_output
→ alternativePathResult
```

## 15. GraphState 타입 명세와 백엔드 입출력 JSON 명세

### 15.1 GraphState 타입 정의

13.2의 상태 스키마에 타입을 부여한다. LangGraph의 `TypedDict` 기반 상태로 구현하며, 누적 필드는 리듀서(add)로 병합한다.[cite:33]

```python
from typing import TypedDict, Annotated, Optional
from operator import add

class GraphState(TypedDict):
    # 입력 (요청 시 확정)
    userId: int
    jobPostingInput: dict            # { sourceType: "url|text|file", value: str }
    selectedExperienceIds: list[int]
    preparationPeriodWeeks: int
    availableHoursPerWeek: int

    # 중간 산출물 (노드가 채움, Optional)
    normalizedJobPosting: Optional[dict]
    normalizedUserProfile: Optional[dict]
    gapAnalysisResult: Optional[dict]
    roadmapResult: Optional[dict]
    alternativeJobs: Optional[list[dict]]

    # 제어/누적 (리듀서로 병합)
    followUpQuestions: list[dict]
    sources: Annotated[list[dict], add]
    toolLog: Annotated[list[dict], add]
    warnings: Annotated[list[dict], add]
    retryCount: dict[str, int]        # { nodeName: count }
    status: str                       # 현재 진행 단계 코드
    isComplete: bool
```

- `sources`, `toolLog`, `warnings`는 여러 노드가 이어 붙이므로 `Annotated[..., add]` 리듀서를 쓴다.[cite:33]
- `retryCount`는 노드 이름별 카운터로, 재시도 상한 판단에 쓴다.[cite:21]

### 15.2 백엔드 → AI 서버 요청 명세

회의 10.2의 입력 예시를 그대로 계약으로 고정한다.[cite:21]

```json
POST /api/v1/analyze
{
  "userId": 1,
  "jobPostingInput": { "sourceType": "url", "value": "https://..." },
  "selectedExperienceIds": [3, 7, 9],
  "preparationPeriodWeeks": 16,
  "availableHoursPerWeek": 20,
  "options": { "includeAlternatives": true }
}
```

### 15.3 AI 서버 → 백엔드 응답 명세

회의 10.3의 출력 필드를 최종 스키마로 확정한다.[cite:21]

```json
{
  "analysisId": "uuid",
  "status": "completed | need_more_info | failed",
  "requirements": [],
  "strengths": [],
  "gaps": [],
  "roadmap": [],
  "alternativeJobs": [],
  "followUpQuestions": [],
  "sources": [],
  "warnings": [],
  "meta": {
    "retriedNodes": [],
    "generatedAt": "2026-07-13T00:00:00Z",
    "modelVersion": ""
  }
}
```

`status`가 `need_more_info`면 백엔드는 `followUpQuestions`를 사용자에게 노출하고, 사용자의 답을 모아 같은 엔드포인트로 재요청(`analysisId` 포함)하여 그래프를 이어서 재개한다.[cite:21][cite:33]

### 15.4 계약 우선 개발 원칙

회의 10.1의 "백엔드와 AI 서버는 분리하고, 입출력 명세를 먼저 정의한 뒤 병렬 개발한다" 원칙을 따른다.[cite:21] 위 15.2~15.3 스키마를 **먼저 확정**하고, 양측은 목(mock) 데이터로 병렬 개발한 뒤 연결한다.[cite:21]

## 16. failure_handler / retry_manager 정책

### 16.1 실패 계층 구분

실패를 세 계층으로 나누고 대응을 달리한다.[cite:21]

| 계층 | 예시 | 대응 |
|---|---|---|
| 툴 수준 실패 | URL 요청 실패, 파싱 오류, 검색 타임아웃 | `failure_handler`가 재시도 → fallback 툴 |
| 노드 수준 실패 | 구조화 결과가 스키마 검증 실패 | 해당 노드 재실행(retryCount 증가) |
| 검증 재시도 | Result Verifier의 정합성 위반 | 원인 노드로 되돌아가 재생성 |

### 16.2 재시도 상한과 백오프

```text
- 툴 호출: 최대 2회 재시도, 지수 백오프(1s, 2s)
- 노드: retryCount[node] < MAX_NODE_RETRY(=2) 일 때만 재실행
- 검증 재시도: 전체 그래프에서 MAX_VERIFY_RETRY(=1~2) 초과 시 중단
```

상한 초과 시 실패를 삼키지 않고, 부분 결과 + warning을 반환하거나 사용자에게 알린다.[cite:21]

### 16.3 fallback 우선순위

각 실패 지점에서 안전장치를 둔다. 회의의 결정(공고 파싱 실패 시 원문 붙여넣기로 대체, OCR 실패 허용)을 반영한다.[cite:21]

```text
- 공고 URL 파싱 실패 → 원문 텍스트 붙여넣기 요청
- 파일 추출 실패     → 텍스트 직접 입력 요청
- 내부 검색 부족     → 웹 검색 → 최후에 외부 LLM 검색
- 반복 실패          → followUpQuestions 또는 사용자 알림으로 전환
```

### 16.4 retry_manager 책임

- 노드별 `retryCount`를 상태에서 관리하고 상한을 강제한다.[cite:21]
- 재시도 사유·횟수를 `toolLog`와 응답의 `meta.retriedNodes`에 기록해 추적 가능하게 한다.[cite:21]
- 재시도가 아니라 "정보 부족"이 원인이면 재시도 대신 `ask_user` 분기로 전환한다.[cite:21]

## 17. 진행 상태(status) 스트리밍과 프론트 에이전트 시각화 연동

### 17.1 상태 코드 정의

회의 12.1의 진행 표시 문구를 상태 코드로 표준화한다.[cite:21]

| status 코드 | 프론트 표시 문구 | 대응 노드 |
|---|---|---|
| `parsing_job` | 채용공고 분석 중 | `parse_job_posting` |
| `building_profile` | 사용자 경험 조회 중 | `build_user_profile` |
| `need_info` | 부족한 정보 확인 중 | `ask_user` |
| `analyzing_gap` | 강점·부족 역량 분석 중 | `analyze_gap` |
| `fetching_company` | 기업 정보 검색 중 | Gap Analyzer 내부 |
| `planning_roadmap` | 준비 로드맵 생성 중 | `plan_roadmap` |
| `finding_alternatives` | 유사 공고 비교 중 | `find_alternatives` |
| `verifying` | 최종 결과 검증 중 | `verify_result` |
| `completed` | 완료 | `assemble_output` |

### 17.2 스트리밍 방식

LangGraph는 노드 실행마다 상태 업데이트를 스트리밍할 수 있으므로, 이를 백엔드가 중계해 프론트로 전달한다.[cite:33]

```text
LangGraph node stream
→ AI 서버가 각 단계 status 이벤트 방출
→ 백엔드가 SSE(Server-Sent Events) 또는 WebSocket으로 중계
→ 프론트가 진행 상태 UI 갱신
```

- MVP는 구현 부담이 적은 **SSE** 우선. 실시간 협업(RTC)까지 확장하면 WebSocket으로 승격한다.[cite:21]
- 각 이벤트는 `{ status, message, nodeName, timestamp }` 형태로 전달한다.

### 17.3 에이전트 시각화 연동

회의 12.2의 "여러 에이전트가 업무를 넘겨받는" 시각화를 위해, 상태 이벤트에 **핸드오프 정보**를 담는다.[cite:21]

```json
{ "status": "analyzing_gap", "from": "build_user_profile", "to": "analyze_gap", "message": "이력 검증 → 갭 분석 담당에게 전달" }
```

프론트는 이 `from → to`를 이용해 가상의 담당자(캐릭터)가 작업을 넘겨받는 흐름으로 표현할 수 있다. 캐릭터 디자인·모션은 미확정이므로, 연동 계약(이벤트 스키마)만 먼저 고정한다.[cite:21]

## 18. RAG·프롬프트 성능 평가 지표와 테스트 데이터

면담에서 "RAG·에이전트 성능을 지표로 반복 개선한 경험"이 면접·상호평가에서 강한 차별화 축으로 평가된다고 강조되었다.[cite:18] 따라서 평가 체계를 설계 단계에서 함께 정의한다.

### 18.1 평가 대상과 지표

| 평가 대상 | 지표 | 측정 방법 |
|---|---|---|
| 공고 파싱 | 필수/우대 추출 정확도(F1) | 정답 라벨 대비 비교 |
| 검색(RAG) | Recall@k, Precision@k, MRR | 정답 근거 문서 포함 여부 |
| 갭 판정 | 판정 정확도, 근거 적합도 | 사람 라벨과 일치율 |
| 답변 근거성 | Groundedness / Faithfulness | 근거 문장 대비 환각 여부 |
| 로드맵 품질 | 제약 준수율, 완결성 | 시간 예산 초과·필드 누락 검사 |
| 표현 정책 | 금지 표현 위반율 | 규칙·LLM 판정 |

### 18.2 테스트 데이터 구성

```text
- 채용공고 샘플 세트: 직무·연차·도메인 다양성 확보(수십 건 규모)
- 사용자 프로필 샘플: 강점/부족이 뚜렷한 케이스 + 애매한 케이스
- (공고 × 프로필) 페어별 정답 라벨: 충족/부족 요구사항, 기대 강점/gap
- 근거 문서 정답셋: 각 질의에 대한 정답 근거 문서 id
- 회귀 세트: 개선 전후 성능 비교용 고정 세트
```

정보가 없는 필드는 추측하지 않고 `null`로 라벨링한다(회의 8.4 원칙 준용).[cite:21]

### 18.3 실험·개선 루프

```text
평가셋 실행
→ 지표 측정(baseline)
→ 프롬프트/검색 방식/에이전트 구조 변경
→ 동일 회귀셋 재측정
→ 개선 수치 비교·기록
→ 발표용 시각화(개선 전후 표·그래프)
```

면담 조언대로, 화면만으로는 드러나지 않는 이 개선 과정을 **발표·상호평가에서 수치와 그래프로 시각화**하는 것을 전제로 지표를 남긴다.[cite:18]

## 19. 다음 설계 순서

핵심 노드와 운영·평가 설계(8~18장)까지 정리했으므로, 다음에 이어서 확정할 항목은 아래가 적절하다.[cite:21]

1. 공통 데이터 스키마(공고·프로필·후기·기업) 필드 확정과 taxonomy 정의[cite:21]
2. 프롬프트 템플릿 실제 작성(에이전트별 시스템/구조화 프롬프트)[cite:21]
3. 데이터 수집·정제 파이프라인과 벡터 DB 적재 설계[cite:21]
4. LangGraph 그래프의 실제 코드 스켈레톤(노드 함수 시그니처, 엣지 등록)[cite:33]
5. 평가 하네스 구현(평가셋 로더, 지표 계산, 리포트 생성)[cite:18]

## 20. 최종 한 줄 정리

이 프로젝트의 기본 구현 전략은 다음과 같이 정리할 수 있다.[cite:21][cite:31][cite:33]

> **LangGraph로 오케스트레이터와 에이전트 간 흐름(분기·루프·상태·재시도·스트리밍)을 설계하고, LangChain으로 각 에이전트 내부의 파싱·구조화·비교·계획·검증 체인을 구현하며, 계약(입출력 명세)과 성능 평가 체계를 처음부터 함께 고정한다.**[cite:31][cite:33]
