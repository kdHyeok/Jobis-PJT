# backend/

JOBIS 웹 서비스의 Spring Boot 백엔드입니다. 프론트엔드 화면(HTML/JS)도 `src/main/resources/static/`에서 함께 서빙합니다.

## 준비물

- Java 17
- MySQL 8
- 가짜 AI 서버 실행 중이어야 함 → [fake-ai/README.md](../fake-ai/README.md)

## 1. DB 생성

MySQL에 접속해서 데이터베이스만 만든다. (테이블은 실행 시 Flyway가 자동 생성)

```sql
CREATE DATABASE jobiss CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

기본 접속 정보 (`src/main/resources/application.yml`)

| 항목 | 값 |
|---|---|
| url | `localhost:3306/jobiss` |
| username | `root` |
| password | `ssafy` |

다르면 환경변수로 덮어쓴다.

```bash
# 예시
set DB_USERNAME=root
set DB_PASSWORD=본인비밀번호
```

## 2. 실행

```bash
gradlew.bat bootRun     # macOS/Linux: ./gradlew bootRun
```

→ `http://localhost:8080`

## 3. 접속

```text
http://localhost:8080/login.html
```

회원가입 → 로그인 → `커리어 저장소`에 이력서 텍스트 붙여넣고 등록 → `새 분석`에서 공고 URL/원문 입력 → 분석 진행.

## 구조 메모

- 스키마의 주인은 Flyway(`src/main/resources/db/migration`). Hibernate는 `ddl-auto: validate`로 검증만 한다.
- AI 분석은 백엔드가 원문만 AI 서버(WebSocket `:8000`)로 전달하고, 분석·파싱은 전부 AI 서버가 담당한다.
- JWT 시크릿 등 민감 값은 환경변수로 덮어쓸 수 있다 (`JWT_SECRET` 등).
