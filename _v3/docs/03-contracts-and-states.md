# 03. 계약과 상태 전이

- 계약 버전 제안: `jobis.ai.v3alpha1`
- 원칙: 코딩 전에 입력·출력·권한·상태를 먼저 고정한다.
- 표기: 아래 JSON은 필드 의미를 설명하는 설계 예시이며 구현 시 JSON Schema와 Pydantic,
  Java record로 같은 계약을 생성하거나 상호 검증한다.

## 1. SourceDocument

수집된 원본과 추출 결과를 표현한다. 아직 신뢰된 공고가 아니다.

```json
{
  "contractVersion": "jobis.ai.v3alpha1",
  "sourceDocumentId": "src_...",
  "inputType": "URL",
  "originalInput": "https://example.com/posting/123",
  "canonicalUrl": "https://example.com/posting/123",
  "capturedAt": "2026-08-04T12:00:00+09:00",
  "extractionRevision": 1,
  "extractorVersion": "source-extractor-3.0.0",
  "canonicalInputHash": "sha256:...",
  "rawText": "추출된 전체 텍스트",
  "contentHash": "sha256:...",
  "segments": [],
  "warnings": [],
  "status": "EXTRACTED"
}
```

### ExtractionSegment

```json
{
  "segmentId": "seg_001",
  "text": "지원 자격: 신입",
  "method": "VLM",
  "sourceLocator": {
    "page": 1,
    "imageIndex": 0,
    "boundingBox": [0.12, 0.31, 0.88, 0.37],
    "charStart": null,
    "charEnd": null
  },
  "confidence": 0.81,
  "overlapGroup": "tile_2_3",
  "warnings": []
}
```

- `method`: `DIRECT_TEXT | HTML | IFRAME | OCR | VLM | USER_PASTE`
- 이미지 좌표를 제공할 수 없으면 명시적으로 `null`을 사용한다.
- `confidence`가 없는 공급자는 값을 만들지 않고 `null`을 사용한다.
- 중복 타일에서 나온 문장은 `overlapGroup`으로 추적한다.
- `canonicalInputHash`는 진입 화면과 revision을 포함하지 않는다. 같은 입력과 extractor version은
  채팅과 채용공고 페이지에서 같은 캐시 키를 가진다.
- 내부 수집 API는 `POST /v1/sources/acquire`, 사용자 확인 API는
  `POST /v1/sources/{sourceDocumentId}/verify` 하나를 두 진입점이 공용으로 사용한다.
- URL은 http/https만 허용하며 사설·loopback·link-local 주소, 자격 증명 포함 URL, 크기 제한을
  넘는 응답을 거부한다.
- AI 서버는 원문을 영속 저장하지 않는다. Spring이 문서 revision과 snapshot 체인을 저장하고,
  AI는 `previousSnapshotId`를 포함한 새 불변 결과를 반환한다.

## 2. VerifiedPostingSnapshot

사용자가 분석 기준으로 확인한 원문 버전이다. 이후 분석은 반드시 snapshot ID를 참조한다.

```json
{
  "verifiedSnapshotId": "vps_...",
  "sourceDocumentId": "src_...",
  "sourceRevision": 1,
  "previousSnapshotId": null,
  "verifiedText": "사용자가 확인하거나 수정한 공고 원문",
  "corrections": [
    {
      "field": "experience",
      "before": "경력 19년",
      "after": "신입",
      "reason": "OCR_CORRECTION"
    }
  ],
  "verifiedBy": "USER",
  "verifiedAt": "2026-08-04T12:03:00+09:00",
  "snapshotHash": "sha256:..."
}
```

- `verifiedBy`: `USER | OPERATOR | TRUSTED_DIRECT_SOURCE`
- 직접 텍스트 API처럼 출처 정확성을 보장할 수 있을 때만 `TRUSTED_DIRECT_SOURCE`를 허용한다.
- URL HTML과 VLM 결과는 기본적으로 사용자 확인을 요구한다.
- 수정할 때 기존 snapshot을 덮어쓰지 않고 새 revision을 만든다.

## 3. StructuredPosting

```json
{
  "analysisVersion": "posting-interpreter-3.0.0",
  "verifiedSnapshotId": "vps_...",
  "company": {
    "displayName": "이스트게임즈",
    "canonicalCompanyId": null,
    "evidenceIds": ["seg_001"],
    "confidence": 0.98
  },
  "postingTitle": "웹 개발자",
  "positions": [],
  "sharedConditions": [],
  "applicationDeadline": null,
  "ambiguities": [],
  "warnings": []
}
```

### Position

```json
{
  "positionId": "pos_backend",
  "sourceTitle": "백엔드 개발",
  "role": {
    "family": "SOFTWARE_ENGINEERING",
    "specialization": "WEB_BACKEND",
    "canonicalRoleId": "role.web_backend",
    "status": "CANDIDATE",
    "confidence": 0.91,
    "evidenceIds": ["seg_010", "seg_011"]
  },
  "experience": {
    "kind": "NEW_GRADUATE_OR_EXPERIENCED",
    "minMonths": null,
    "maxMonths": null,
    "confidence": 0.96,
    "evidenceIds": ["seg_012"]
  },
  "responsibilities": [],
  "requirements": [],
  "warnings": []
}
```

### Role

- `family`는 넓은 계열이고 `specialization`은 실제 경로다.
- 예: `SOFTWARE_ENGINEERING/WEB_BACKEND`, `GAME_ENGINEERING/GAME_SERVER`,
  `GAME_ENGINEERING/GAME_CLIENT`, `SECURITY/SECURITY_ENGINEERING`.
- taxonomy에 없으면 `canonicalRoleId=null`, `status=NEW_CANDIDATE`로 보존한다.
- 모집 직무가 아닌 협업 대상, 사용 기술, 조직 이름의 언급은 role evidence가 될 수 없다.

### ExperienceRequirement

- `kind`: `NEW_GRADUATE | EXPERIENCE_REQUIRED | RANGE | NO_RESTRICTION |
  NEW_GRADUATE_OR_EXPERIENCED | UNKNOWN`
- 숫자는 월 단위로 정규화하지만 원문 표현과 evidence를 보존한다.
- 회사 업력, 서비스 운영 연수, 팀원 경력은 포지션 경력 evidence로 허용하지 않는다.
- 직무별 연수가 다르면 각 Position 안에 별도로 저장한다.

### AtomicRequirement

```json
{
  "requirementId": "req_...",
  "sourceText": "Spring Boot 기반 REST API 개발 경험과 협업 능력",
  "atomicText": "Spring Boot 기반 REST API 개발 경험",
  "obligation": "REQUIRED",
  "category": "TECHNICAL_CAPABILITY",
  "appliesToPositionIds": ["pos_backend"],
  "evidenceIds": ["seg_021"],
  "confidence": 0.93,
  "normalizationStatus": "PENDING",
  "warnings": []
}
```

- `obligation`: `REQUIRED | PREFERRED | INFORMATIONAL`
- `category`: `TECHNOLOGY | TECHNICAL_CAPABILITY | RESPONSIBILITY | DOMAIN_KNOWLEDGE |
  CREDENTIAL | EXPERIENCE | PORTFOLIO | BEHAVIORAL | EMPLOYMENT_CONDITION | OTHER`
- 한 문장에 기술과 정성적 조건이 섞이면 여러 AtomicRequirement로 분해한다.
- 원문에 없는 requirement를 선행학습이라는 이유로 공고 분석 단계에서 추가하지 않는다.

## 4. Ambiguity와 추가 질문

```json
{
  "ambiguityId": "amb_...",
  "type": "POSITION_SELECTION",
  "blocking": true,
  "reason": "서로 다른 두 모집 포지션의 요건과 경력이 존재함",
  "candidateIds": ["pos_frontend", "pos_backend"],
  "evidenceIds": ["seg_010", "seg_030"],
  "question": {
    "inputType": "CHOICE",
    "text": "어느 직무 기준으로 준비도를 분석할까요?",
    "options": [
      {"value": "pos_frontend", "label": "프론트엔드"},
      {"value": "pos_backend", "label": "백엔드"}
    ]
  }
}
```

- `type`: `SOURCE_VERIFICATION | POSITION_SELECTION | EXPERIENCE_CONFLICT |
  REQUIREMENT_SCOPE | USER_EVIDENCE | OTHER`
- 질문은 답변이 최종 결과를 실제로 바꿀 때만 생성한다.
- 포지션이 하나뿐이면 협업 대상이 여러 개 언급돼도 직무 질문을 만들지 않는다.
- 같은 ambiguity ID는 같은 답변 이후 다시 묻지 않는다.

## 5. PostingResolution

구조화된 공고에서 실제 사용자 선택이 필요한 항목만 한 번에 하나씩 반환한다.

```json
{
  "status": "AWAITING_ANSWER",
  "selectedPositionId": null,
  "selectedExperienceTrack": null,
  "activeAmbiguity": {
    "ambiguityId": "amb-position-...",
    "type": "POSITION_SELECTION",
    "blocking": true,
    "candidateIds": ["pos-1", "pos-2"]
  },
  "resolvedAmbiguityIds": []
}
```

- 질문 순서는 `POSITION_SELECTION → EXPERIENCE_TRACK_SELECTION`이다.
- 단일 포지션, 신입 전용, 경력 전용은 질문 없이 자동 선택한다.
- 답변은 `ambiguityId`, 선택값, 답변 시각을 저장하며 동일 ID의 중복 답변을 거부한다.
- 질문 ID는 verified snapshot과 후보 ID에서 결정되므로 재호출과 새로고침에도 안정적이다.
- 선택 경로와 무관하거나 이전 revision의 답변은 `ANALYSIS_STALE_RESULT`다.
- 구조에서 신뢰할 수 있는 선택지를 만들 수 없는 경우 임의 질문·임의 확정을 하지 않고
  `UNKNOWN`을 보존한다.

## 6. 사용자 역량 근거 상태

```json
{
  "competencyId": "skill.java",
  "displayName": "Java",
  "scopeDefinition": "Java 문법·타입·컬렉션·객체지향 프로그래밍 범위",
  "claimState": "CLAIMED",
  "evidenceState": "EVIDENCED",
  "verificationState": "NOT_VERIFIED",
  "claimedLevel": 2,
  "verifiedLevel": 0,
  "evidenceRefs": ["career_fragment_..."],
  "confidence": 0.82
}
```

- `claimState`: `CLAIMED | NOT_CLAIMED | UNKNOWN`
- `evidenceState`: `EVIDENCED | NO_EVIDENCE | UNKNOWN`
- `verificationState`: `VERIFIED | PARTIALLY_VERIFIED | NOT_VERIFIED | NOT_APPLICABLE`
- 이 세 축을 하나의 `MET`로 축약하지 않는다.
- `UserEvidenceBundle`은 Spring이 RLS로 격리해 조회한 한 사용자의 evidence set과 revision만
  전달한다. AI 서버는 사용자 근거를 공용 캐시나 다른 사용자 요청에 보존하지 않는다.
- 모델은 requirement와 competency/formal fact 사이의 의미 연결 후보만 만든다. 상태 승격과
  점수는 후보 ID 무결성을 검사한 결정론적 컴파일러가 계산한다.

## 7. RequirementAssessment와 FitAssessment

```json
{
  "requirementId": "req_...",
  "status": "PARTIAL",
  "required": true,
  "matchedCompetencies": ["skill.java"],
  "userEvidenceRefs": ["career_fragment_..."],
  "postingEvidenceIds": ["seg_021"],
  "reason": "프로젝트 사용 근거는 있으나 요구 수준 검증은 완료되지 않음",
  "confidence": 0.78
}
```

- `status`: `VERIFIED_MET | EVIDENCED | CLAIMED_ONLY | PARTIAL | NOT_MET | UNKNOWN |
  NOT_APPLICABLE`
- `UNKNOWN`은 점수 분모에서 제외하되, 중요한 필수요건이면 사용자에게 근거 질문을 제안한다.
- `NOT_MET`은 명시적인 부재 답변이나 요구 수준 미달 근거가 있을 때만 사용한다.

FitAssessment는 다음을 포함한다.

- 선택한 `positionId`
- 형식적 지원 자격 충족 여부
- 필수·우대요건별 평가
- 주장 기반 준비도와 검증 기반 준비도를 구분한 지표
- 강점, 공백, 불확실 항목
- `APPLY_NOW | STRENGTHEN_THEN_APPLY | ALTERNATIVE_PATH | UNKNOWN` 판정안
- 판정에 사용한 정책 버전

최종 백분율과 경력 관문 판정은 Spring의 정책 버전이 계산한다. AI는 근거별 관련성 후보를
제공한다.

독립 v3의 `fit-policy-0.1`은 계약과 회귀 검증을 위한 참조 계산기다. 실제 통합 때 Spring은
같은 입력으로 수치를 재계산하고, AI가 반환한 `verdictProposal`을 최종 판정으로 신뢰하지 않는다.

## 8. CapabilityNormalization

```json
{
  "requirementId": "req_...",
  "sourceCategory": "TECHNOLOGY",
  "disposition": "LEARNING_CAPABILITY",
  "decision": "CANDIDATES_PROPOSED",
  "selectedCanonicalKey": null,
  "candidates": [
    {
      "canonicalKey": "framework.spring_boot",
      "matchType": "AI_DIRECT_SCOPE",
      "confidence": 0.97,
      "reason": "승인된 범위가 공고 요건을 직접 포함함"
    }
  ],
  "newCandidate": null,
  "reviewStatus": "OPERATOR_REVIEW_REQUIRED",
  "evidenceIds": ["seg_..."],
  "reason": "AI 범위 후보는 공용 catalog에 자동 병합하지 않음"
}
```

사전에 없으면 다음처럼 보존한다.

```json
{
  "decision": "NEW_CANDIDATE_PROPOSED",
  "candidates": [],
  "newCandidate": {
    "candidateId": "capability-candidate-...",
    "displayName": "새로운 기술명",
    "proposedKind": "DATABASE",
    "aliases": [],
    "evidenceIds": ["seg_..."],
    "scopeDefinition": "공고에서 요구한 학습·검증 가능 범위",
    "confidence": 0.9
  },
  "reviewStatus": "OPERATOR_REVIEW_REQUIRED"
}
```

- `AUTO_SELECTED`는 원자 요건 전체가 승인된 canonical key·표시명·alias와 동일할 때만 허용한다.
  문장 중간에 Java 같은 이름이 한 번 등장한 경우는 자동 확정하지 않는다.
- AI가 기존 catalog 후보를 제안해도 `selectedCanonicalKey`는 비어 있고 운영자 검토 대상이다.
- 신규 후보에는 안정적인 `candidateId`가 생기므로 사용자 흐름은 검토 완료를 기다리지 않고
  임시 분석·로드맵 초안을 계속 만들 수 있다. 공용 catalog 반영만 보류된다.
- 업무와 포트폴리오는 `PROJECT_CONTEXT`, 경력·자격은 `CAREER_GATE`, 행동 요소는 `FIT_ONLY`,
  고용 조건은 `EMPLOYMENT_INFORMATION`으로 분리한다.

## 9. RoadmapProposal

```json
{
  "proposalId": "rmp_...",
  "basedOnAnalysisId": "analysis_...",
  "basedOnRoadmapVersion": 4,
  "selectedPositionId": "pos_backend",
  "operations": [],
  "excludedRequirements": [],
  "warnings": [],
  "status": "DRAFT"
}
```

각 operation은 다음을 포함한다.

- `action`: `REUSE_NODE | CREATE_NODE | ADD_REQUIREMENT_LINK | CREATE_GATE |
  CREATE_TARGET_PROJECT | ADD_OPPORTUNITY`
- `canonicalKey`, `level`, `scopeDefinition`
- `reason`과 원본 requirement ID
- `requiredFor`와 `preferredFor`
- 선행관계 제안
- 기존 사용자 완료 상태를 변경하지 않는다는 표시

로드맵 에이전트는 좌표를 확정하지 않는다. 백엔드가 기존 그래프와 합쳐 간선·좌표·경력 관문을
계산한다.

## 10. 분석 상태 전이

```text
RECEIVED
  → SOURCE_FETCHING
  → SOURCE_EXTRACTED
  → AWAITING_SOURCE_VERIFICATION
  → SOURCE_VERIFIED
  → STRUCTURING_POSTING
  → AWAITING_POSITION_SELECTION (필요할 때)
  → READY_FOR_ANALYSIS
  → ANALYZING_FIT
  → AWAITING_USER_EVIDENCE (필요할 때)
  → NORMALIZING_CAPABILITIES
  → DRAFT_READY
  → SUCCEEDED

어느 실행 상태에서든:
  → CANCEL_REQUESTED → CANCELLED
  → FAILED_RETRYABLE → QUEUED
  → FAILED_FINAL
```

- `AWAITING_*` 상태는 워커를 점유하지 않는다.
- `RUNNING` 계열 상태는 lease와 heartbeat를 가진다.
- lease가 만료되면 `FAILED_RETRYABLE` 또는 `QUEUED`로 복구한다.
- 질문 횟수와 원문 revision이 바뀌면 캐시 키도 바뀐다.
- 취소 이후 늦게 도착한 AI 응답은 상태를 성공으로 덮어쓰지 못한다.

## 11. ProgressEvent

```json
{
  "eventId": "evt_...",
  "jobId": "job_...",
  "sequence": 12,
  "stage": "POSTING_STRUCTURE",
  "status": "RUNNING",
  "label": "모집 직무와 조건을 정리하고 있어요",
  "detail": "공고 원문 근거를 연결하는 중",
  "occurredAt": "2026-08-04T12:05:00+09:00",
  "elapsedMs": 8100,
  "warnings": []
}
```

- `status`: `PENDING | RUNNING | WAITING | COMPLETED | SKIPPED | FAILED | CANCELLED`
- `sequence`는 작업 안에서 단조 증가한다.
- 새로고침은 마지막 sequence 이후 이벤트와 현재 스냅샷을 함께 조회한다.
- 내부 chain-of-thought는 event에 넣지 않는다.

## 12. 오류 계약

| 코드 | 의미 | 재시도 |
|---|---|---|
| `SOURCE_FETCH_FAILED` | URL/이미지를 가져오지 못함 | 조건부 |
| `SOURCE_EXTRACTION_LOW_CONFIDENCE` | 사용자 확인이 필요한 낮은 추출 신뢰도 | 사용자 입력 |
| `SOURCE_NOT_VERIFIED` | 검증되지 않은 원문으로 분석 요청 | 불가 |
| `POSTING_STRUCTURE_INVALID` | 구조화 결과가 계약을 충족하지 못함 | 자동 제한 재시도 |
| `AMBIGUITY_UNRESOLVED` | 결과를 바꾸는 모호함이 남음 | 사용자 입력 |
| `AI_PROVIDER_NOT_CONFIGURED` | 모델 공급자 설정 없음 | 설정 후 |
| `AI_TIMEOUT` | 모델 호출 제한 시간 초과 | 가능 |
| `AI_PROVIDER_UNAVAILABLE` | 공급자 또는 에이전트 실행 실패 | 가능 |
| `CONTRACT_VALIDATION_FAILED` | 참조·enum·필수 필드 오류 | 자동 제한 재시도 |
| `ANALYSIS_CANCELLED` | 사용자 취소 | 명시적 재시작 |
| `ANALYSIS_STALE_RESULT` | 취소/새 revision 뒤 늦게 도착한 결과 | 불가 |

## 13. 캐시와 idempotency

- Source extraction: `canonicalInputHash + extractorVersion`
- Common posting analysis: `verifiedSnapshotHash + interpreterVersion`
- Position analysis: `verifiedSnapshotHash + positionId + answersHash + analyzerVersion`
- User fit: `commonAnalysisId + userEvidenceRevision + verificationRevision + policyVersion`
- Roadmap draft: `fitAnalysisId + activeTargetsHash + currentRoadmapVersion + composerVersion`

모델명과 프롬프트 버전은 분석 메타데이터에 남긴다. 캐시가 적중하더라도 사용자별 적합도와
권한 검사는 다시 수행한다.
