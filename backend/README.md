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

## 2. 로컬 환경 파일 준비 (.env)

DB 접속 정보와 JWT 시크릿은 코드에 기본값이 없으므로 `.env` 파일로 주입한다.
`backend` 폴더에서 예시 파일을 복사한 뒤 본인 로컬 값을 채운다.

```bash
# Windows PowerShell: Copy-Item .env.example .env
cp .env.example .env
```

```dotenv
DB_URL=jdbc:mysql://localhost:3306/jobiss?serverTimezone=UTC&characterEncoding=UTF-8
DB_USERNAME=root
DB_PASSWORD=본인비밀번호
JWT_SECRET=32자_이상의_임의_문자열
```

> **주의: `JWT_SECRET`은 반드시 32자(256비트) 이상이어야 한다.** 짧으면 서버 시작 시
> `WeakKeyException`으로 실행이 실패한다.

임의의 JWT 시크릿 생성 방법 — 아래 명령 출력값을 복사해서 `JWT_SECRET=` 뒤에 붙여넣는다.

Windows PowerShell:

```powershell
[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }))
```

macOS/Linux:

```bash
openssl rand -base64 48
```

> `.env`는 Git에서 무시된다. 저장소·메신저·이슈에 절대 올리지 않는다.
> 운영 환경에서는 `.env`를 배포하지 않고 systemd `EnvironmentFile`로 주입한다.

## 3. 실행

`local` 프로필로 실행해야 `.env`를 읽는다.

```bash
gradlew.bat bootRun --args="--spring.profiles.active=local"     # macOS/Linux: ./gradlew bootRun --args='--spring.profiles.active=local'
```

→ `http://localhost:8080`

## 4. 접속

```text
http://localhost:8080/login.html
```

회원가입 → 로그인 → `커리어 저장소`에 이력서 텍스트 붙여넣고 등록 → `새 분석`에서 공고 URL/원문 입력 → 분석 진행.

## 구조 메모

- 스키마의 주인은 Flyway(`src/main/resources/db/migration`). Hibernate는 `ddl-auto: validate`로 검증만 한다.
- AI 분석은 백엔드가 원문만 AI 서버(WebSocket `:8000`)로 전달하고, 분석·파싱은 전부 AI 서버가 담당한다.
- JWT 시크릿 등 민감 값은 환경변수로 덮어쓸 수 있다 (`JWT_SECRET` 등).
