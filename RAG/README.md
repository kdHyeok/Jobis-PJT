# JOBIS RAG

채용 공고를 PostgreSQL/pgvector에 적재하고, dense 검색과 BM25를 결합해
공고를 검색하는 독립형 RAG 프로토타입입니다. 현재 Spring 백엔드나
`fake-ai` 런타임에는 연결되어 있지 않으므로 이 디렉터리의 실행 여부가
기존 백엔드 동작에 영향을 주지는 않습니다.

## 준비 사항

- Python 3.11
- PostgreSQL과 `pgvector` 확장
- 임베딩할 채용 공고 JSON 파일
- 생성 및 LLM 평가를 실행할 경우 SSAFY GMS 키

Windows PowerShell에서 최초 한 번 실행합니다.

```powershell
cd C:\Users\SSAFY\work\gitLab\S15P11C202\RAG

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Copy-Item .env.example .env
```

`.env`의 `PG_DSN`과, GMS 기능을 사용할 경우 `GMS_KEY`를 실제 환경에 맞게
설정합니다. `.env`는 Git에 포함되지 않습니다.

## 데이터베이스 구성

아래 예시는 로컬 개발용 계정과 DB를 처음 만드는 명령입니다.

```powershell
psql -U postgres -c "CREATE USER jobrag WITH PASSWORD 'jobrag_local_dev';"
psql -U postgres -c "CREATE DATABASE jobrag OWNER jobrag;"
psql -U jobrag -d jobrag -f schema.sql
```

이미 사용자나 DB가 있다면 생성 명령은 생략하고 `schema.sql`만 적용하면 됩니다.
`CREATE EXTENSION vector` 권한 오류가 나면 PostgreSQL 관리자 계정으로 확장을
먼저 설치해야 합니다.

## 적재와 검색

저장소에는 기본 입력 파일이 포함되어 있지 않으므로 JSON 경로를 명시합니다.

```powershell
python run_embed.py C:\path\to\all_job_postings.json
python run_search.py "서울에서 스프링부트 하는 3년차 백엔드 개발자"
python run_search.py --check
```

웹 검색 화면은 다음과 같이 실행합니다.

```powershell
python webapp/server.py
```

브라우저에서 `http://127.0.0.1:8766`으로 접속합니다. 답변 생성은 `GMS_KEY`가
있어야 하지만, 키가 없어 생성에 실패해도 검색 결과 자체는 응답에 남습니다.

추가 개발 도구:

```powershell
python webapp/explorer_server.py
python webapp/rag_adapter_server.py
```

- 데이터 탐색기: `http://127.0.0.1:8768`
- RAG 어댑터 테스트: `http://127.0.0.1:8770`

## 평가

v4 평가는 pool 구성, LLM 판정, 게이트 확인, 측정 순서로 실행합니다.

```powershell
python -m eval.run --build-pool
python -m eval.run --judge
python -m eval.anchor --session all
# 생성된 eval\anchor\session_*.csv의 label과 timestamp를 사람이 작성
python -m eval.anchor --score
python -m eval.run --gates
python -m eval.run --measure
```

`--judge`에는 GMS 키가 필요합니다. 현재 저장소의 앵커 CSV에는 사람 라벨이
채워져 있지 않으므로, 라벨링과 `--score`를 끝내기 전에는 사람 앵커 게이트가
실패합니다. 게이트가 실패하면 `report.json`은 생성되지 않습니다. 자세한 기준과
한계는 [eval/PLAN.md](eval/PLAN.md)에 정리되어 있습니다.

Tier 0 계약 검사는 현재 프로필 입력 A/B를 받는 `search_fn` 연결이 끝나지 않아
기본 실행 결과가 `incomplete`입니다. 건너뛴 검사를 전체 통과로 간주하지 않습니다.

## 현재 통합 경계

- `jobrag.rag_adapter`의 현재 계약은 `sub_roles` 기반 대체 공고 검색입니다.
- 프로필 입력 A/B를 받는 명세 어댑터는 아직 구현되지 않았습니다.
- Spring 백엔드 및 `fake-ai`와의 운영 연결은 별도 통합 작업이 필요합니다.
- 실제 평가에는 PostgreSQL 데이터, 모델 다운로드, GMS 접근이 필요합니다.
