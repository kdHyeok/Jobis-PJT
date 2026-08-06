# Spring JDBC와 PostgreSQL SQL 안전 규칙

- 날짜: 2026-08-02
- 상태: 결정됨 · 자동 검증 적용
- 범위: Spring `JdbcClient`, PostgreSQL JSONB, nullable SQL parameter

## 배경

공고 중복 조회를 구현하면서 PostgreSQL JSONB 존재 연산자 `?`를 Java의 이름 있는
파라미터 SQL 안에서 사용했다. Spring JDBC는 이 문자를 전통적인 positional
placeholder로 해석했고, 같은 SQL에 `:userId` 같은 이름 있는 파라미터도 존재해
다음 런타임 오류가 발생했다.

```text
Not allowed to mix named and traditional ? placeholders
```

이전에는 null 값을 `:value is null`로 직접 판별하는 쿼리에서 PostgreSQL이 파라미터
타입을 결정하지 못하는 오류도 발생했다. 두 문제 모두 SQL 자체는 자연스러워 보이고
Java 컴파일로 발견되지 않으며 해당 실행 경로가 호출될 때만 나타난다는 공통점이 있다.

## 결정

1. 이름 있는 파라미터를 사용하는 Java SQL에서는 JSONB 연산자 `?`, `?|`, `?&`를
   사용하지 않는다.
2. JSONB 키 검사는 `jsonb_exists`, `jsonb_exists_any`, `jsonb_exists_all`로 작성한다.
3. null 가능 파라미터를 SQL 안에서 `:value is null`로 검사하지 않는다.
4. 입력 조건에 따라 SQL을 분기하거나 별도 boolean 파라미터와 타입이 확정된 값을
   전달한다.
5. Java 메인 소스를 검사하는 `SpringJdbcSqlGuardrailTest`로 금지 패턴의 재도입을
   차단한다.
6. SQL 변경은 실제 PostgreSQL 통합 테스트로 최종 검증한다.

## 올바른 예

```sql
and jsonb_exists(job.result_data, 'job')
and jsonb_exists(job.result_data, 'competencyProposal')
```

```java
boolean hasMessage = message != null && !message.isBlank();

jdbc.sql("""
    update analysis_jobs
    set stage_message = case
        when :hasMessage then :message
        else stage_message
    end
    where id = :jobId
    """)
    .param("hasMessage", hasMessage)
    .param("message", hasMessage ? message : "")
    .param("jobId", jobId)
    .update();
```

## 금지 예

```sql
and job.result_data ? 'job'
and (:sourcePlatform is null or source_platform = :sourcePlatform)
```

## 결과

- 공고 등록 단계의 500 오류 원인을 정적 테스트에서 발견할 수 있다.
- null 입력과 캐시 재사용 경로를 별도 검증 대상으로 취급한다.
- 새로운 대화나 다른 AI 에이전트도 저장소 루트의 `AGENTS.md`를 통해 동일한 규칙을
  먼저 확인할 수 있다.

