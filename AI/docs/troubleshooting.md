# 트러블슈팅 로그

> 실제로 겪은 문제와 그 원인·해결을 기록한다. 설계 의도는 `agent-derivation-and-tools.md`가
> 정본이고, 이 문서는 "왜 이렇게 바뀌었는지"의 사건 기록(케이스 스터디)에 가깝다.

---

## 2026-07-20 — 도메인 키워드 임베딩 매칭이 관련 없는 문장에 더 높은 점수를 줌 → LLM 폴백으로 전환

### 증상

`gap_matcher`의 3차 도메인 키워드 매칭(`domainKeywords` 비교)을 임베딩 유사도로 구현하려고
GMS(SSAFY API 게이트웨이) 경유 OpenAI 임베딩을 실제로 연결한 뒤 실측했더니, **관련 없는
문장이 관련 있는 문장보다 더 높은 유사도 점수**를 받는 역전이 반복 재현됨.

```
0.271  [관련]  '이벤트 드리븐 아키텍처 설계 경험' vs 'Kafka를 활용해 비동기 메시지 처리 파이프라인을 구축했습니다'
0.364  [무관]  '이벤트 드리븐 아키텍처 설계 경험' vs 'React로 프론트엔드 UI를 개발했습니다'   ← 무관이 더 높음
```

### 조사 과정

1. **1차 가설: 비교 대상이 너무 짧아서 그런가?** (단일 키워드 "커머스" vs 긴 문장)
   → 키워드를 짧은 문장으로 확장("커머스" → "커머스 도메인 경험")해서 재시도. **개선 안 됨**,
   같은 역전 패턴 재현.
2. **2차 가설: 모델이 작아서(`text-embedding-3-small`) 그런가?**
   → `text-embedding-3-large`로 교체(코드 변경 없이 `.env`의 `EMBED_MODEL`만 변경). **개선 안
   됨** — 오히려 관련 최소값(0.205)과 무관 최대값(0.358)의 격차가 더 벌어짐.
3. **결론**: 모델 크기·쿼리 길이 문제가 아니라, **짧은 도메인 키워드 vs 기술 문장을 코사인
   유사도로 세밀하게 구분하는 태스크 자체가 범용 임베딩(OpenAI `text-embedding-3-*`)에
   약하다**고 판단. 두 모델 다 "기술 문장처럼 생겼다"는 표면적 유사성에 끌려가는 것으로
   추정(둘 다 짧은 개발 경력 서술문이라 도메인이 달라도 벡터가 가까워짐).

### 해결

이 판정(도메인 키워드 관련성)에 한해 **LLM 구조화 출력으로 전환**. `src/jobis_ai/semantic_judge.py`
신규 작성:

- `judge_domain_relevance(topic, evidence_texts) -> list[int] | None`
- 자유 서술이 아니라 **관련 문장의 인덱스 배열만** 강제 반환(구조화 출력) — 이유를 지어내지
  못하게 막음
- 기존 읽기 계층 인프라(`structured.run_structured`) 그대로 재사용 — 새 LLM 호출 경로를
  따로 안 만듦
- LLM 미설정/실패 시 예외 대신 `None`("모른다") 반환 → `gap_matcher`가 `not_met`이 아니라
  `uncertain`으로 처리

`gap_matcher._match_domain_keyword`는 **1차 포함 매칭(룰)이 여전히 먼저**고, 그게 실패했을
때만 이 LLM 폴백을 탄다. `Match.method` 필드에 `"keyword"`/`"llm_semantic"`/`"undecidable"`을
남겨 어느 경로로 판정했는지 항상 추적 가능하게 함.

**재검증 결과** (같은 Kafka/React 케이스):
```
'이벤트 드리븐 아키텍처' → met, matched=[ev-2(Kafka)]   — ev-1(React)은 정확히 제외됨
'블록체인'               → not_met                       — 무관한 키워드는 정확히 걸러짐
```

### 왜 이게 `§0`("판단 계층에 LLM 금지") 원칙의 예외인가

이 프로젝트 전체는 "판단(Decide) 계층은 결정론이어야 한다"를 핵심 원칙으로 삼아왔다
(`agent-derivation-and-tools.md` §0). 이번 결정은 그 원칙을 **인지한 상태로, 국소적으로**
깬 것이다 — 근거는 추측이 아니라 위 실측(같은 모델을 두 번 바꿔봐도 재현되는 신호 부족)이다.
`semantic_judge.py` 상단 docstring에 이 예외의 범위와 이유를 명시해뒀다: **이 패턴을 다른
판단 노드로 함부로 넓히면 안 된다.**

### 부수적으로 발견한 버그: 테스트가 실제 GMS API를 호출하고 있었음

GMS 연결(`.env`의 `EMBED_PROVIDER=openai` + 실제 `GMS_KEY`) 이후 `pytest`가 3초 → **33초**로
느려짐. 원인: `tests/conftest.py`가 `get_llm`만 미설정으로 강제하고 있었고, **임베딩은 아무도
막고 있지 않아서** 기존 임베딩 관련 테스트(`test_gap_matcher.py`의 uncertain 판정 테스트 등)가
전부 진짜 네트워크 호출을 하고 있었다. 결과도 실제 임베딩 점수 기준으로 달라져서
`NullEmbedder` 가정하에 짠 assertion들이 깨짐.

**해결**: `conftest.py`에 `force_null_embedder` 픽스처 추가 — `jobis_ai.gap_matcher.get_embedder`
와 `jobis_ai.skill_taxonomy.get_embedder`를 `NullEmbedder`로 강제 패치. `from x import y` 형태로
이름을 각 모듈 네임스페이스에 바인딩해 쓰고 있어서, `jobis_ai.embed.get_embedder` 하나만
패치해선 안 먹혔다 — 각 모듈에서 참조하는 이름을 각각 패치해야 했다.

**교훈**: 외부 API를 하나 연결할 때마다, "테스트가 그걸 진짜로 호출하지 않는지"를 반드시
같이 확인해야 한다. LLM만 막고 임베딩을 빠뜨린 게 이번 사고 원인.

### 남은 것 / 후속 조치

- **`gap_matcher._match_by_embedding`(서술형 요구사항 2차 매칭, 예: "이벤트 드리븐 아키텍처
  설계 경험" 요구사항 문장 자체)는 아직 임베딩 그대로다.** 오늘 재현된 문제와 같은 패턴
  (짧은/중간 길이 텍스트 간 코사인 유사도)이라 똑같이 신뢰도가 낮을 가능성이 높음. 아직
  손 안 댐 — 필요시 같은 방식(LLM 구조화 출력 폴백)으로 전환 검토.
- `agent-derivation-and-tools.md`에 이번 GMS 연결·도메인 키워드 LLM 폴백 내용 아직 미반영.
