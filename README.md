# JOBISS — Web

실행 방법.

## 준비물

- Java 17
- Node.js 18+
- MySQL 8

## 1. DB 생성

MySQL에 접속해서 데이터베이스만 만든다. (테이블은 백엔드 실행 시 Flyway가 자동 생성)

```sql
CREATE DATABASE jobiss CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

기본 접속 정보 (`backend/src/main/resources/application.yml`)

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

## 2. 가짜 AI 서버 실행 (먼저)

```bash
cd fake-ai
npm install
node server.js
```

→ `ws://localhost:8000` 대기. **이게 떠 있어야 분석이 동작한다.**

## 3. 백엔드 실행

```bash
cd backend
gradlew.bat bootRun     # macOS/Linux: ./gradlew bootRun
```

→ `http://localhost:8080`

## 4. 접속

```
http://localhost:8080/login.html
```

회원가입 → 로그인 → `커리어 저장소`에 이력서 텍스트 붙여넣고 등록 → `새 분석`에서 공고 URL/원문 입력 → 분석 진행.

## 실행 순서 요약

1. MySQL 실행
2. `fake-ai` → `node server.js`
3. `backend` → `gradlew.bat bootRun`
4. 브라우저 → `http://localhost:8080/login.html`
