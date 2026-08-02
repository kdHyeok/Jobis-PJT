# RAG 공고 검색 툴 — 인수인계 패키지

AI Agent의 `search_postings` 툴이 호출하는 **실제 RAG 검색 서비스**입니다.
계약은 `RAG_입출력_명세서.md` 그대로입니다 (입력: 직업명 str 또는 profile JSON →
출력: `{"postings": [원본 공고 + score + match_reason]}`, 기본 top_k=3, 0건은 빈 배열).

```
rag_tool_handoff/
├── agent_side/
│   └── search_postings.py     ← Agent_Test/tools/에 덮어쓰기 (mock → 실 RAG 호출)
└── rag_server/                 ← RAG 서버 (아무 위치에나 통째로 두고 실행)
    ├── jobrag/                 검색 엔진 (하이브리드 검색 + 리랭킹 + CRAG 평가자)
    ├── webapp/tool_server.py   HTTP 서버 (POST /search, GET /health)
    ├── db_dump/jobrag.dump     공고 DB 덤프 (원본 + 청크 + 임베딩 벡터 포함, 51MB)
    ├── schema.sql              (참고용 — 덤프 복원하면 따로 실행할 필요 없음)
    ├── requirements.txt
    ├── .env.example
    └── start-rag-server.bat
```

---

## 1. 사전 준비 (1회)

- **PostgreSQL 16+ 와 pgvector 확장** — pgvector는 [릴리스](https://github.com/pgvector/pgvector/releases)
  또는 StackBuilder로 설치
- **Python 3.10+** (3.12에서 검증됨)
- GMS_KEY (이미 보유한 그 키 — CRAG 평가자를 쓸 때만 필요, 검색만이면 없어도 됨)

## 2. DB 복원 (1회)

```bat
"C:\Program Files\PostgreSQL\17\bin\createdb" -U postgres jobrag
"C:\Program Files\PostgreSQL\17\bin\psql"     -U postgres -d jobrag -c "CREATE EXTENSION IF NOT EXISTS vector;"
"C:\Program Files\PostgreSQL\17\bin\pg_restore" -U postgres --no-owner -d jobrag rag_server\db_dump\jobrag.dump
```

> 덤프에 임베딩 벡터까지 들어 있으므로 **재임베딩(모델 추론) 과정이 필요 없습니다.**

## 3. RAG 서버 세팅·기동

```bat
cd rag_server
copy .env.example .env      &rem PG_DSN·GMS_KEY 채우기 (아래 예시)
pip install -r requirements.txt   &rem torch 포함 수 GB — 최초 1회
start-rag-server.bat
```

`.env` 예시:

```
PG_DSN=postgresql://postgres:<비밀번호>@127.0.0.1:5432/jobrag
GMS_KEY=<GMS 키>
```

- 최초 기동 시 임베딩·리랭커 모델을 HuggingFace에서 자동 다운로드(~4GB, 1회)
- 콘솔에 **`warmup done - ready`** 가 뜨면 사용 가능 (warmup 수십 초)
- 확인: `curl http://127.0.0.1:8765/health` → `{"status":"ok","warm":true}`

## 4. 에이전트에 연결

1. `agent_side/search_postings.py` 를 `Agent_Test/tools/search_postings.py` 에 **덮어쓰기**
   (시그니처·입출력 계약 불변 — 다른 파일은 수정 없음, 새 의존성 없음)
2. Agent_Test의 `.env` 에 한 줄 추가:

   ```
   RAG_SEARCH_URL=http://127.0.0.1:8765
   ```

## 5. 동작 확인

```bat
curl -X POST http://127.0.0.1:8765/search -H "Content-Type: application/json" -d "{\"input\": \"backend developer\", \"top_k\": 3}"
```

에이전트에서: `python chat.py` → "데이터 엔지니어 공고 찾아줘" → 실 DB 공고 3건이 나오면 성공.

---

## 운영 특성 (실측)

| 항목 | 값 |
|---|---|
| 검색 지연 (warm) | **~2.2초** — LLM 호출 0회 (임베딩·리랭커는 로컬 모델) |
| CRAG 평가자 켜면 (`"evaluate": true`) | ~6.7초 — 문서별 LLM 채점으로 무관 공고 필터링 |
| RAG 서버가 안 떠 있을 때 | 에이전트는 죽지 않고 "관련 공고 없음" 경로로 진행 (로그에 사유) |
| 기동 순서 | PostgreSQL → RAG 서버(ready 확인) → 에이전트 |
| 공고 데이터를 새로 적재했을 때 | RAG 서버 재시작 필요 (BM25 인덱스가 프로세스 메모리에 있음) |

문의: RAG 담당자에게.
