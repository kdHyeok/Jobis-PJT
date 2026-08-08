# jobis-ai-v3

JOBIS의 새 공고 해석·적합도·로드맵 계약을 기존 AI와 독립적으로 검증하기 위한
contract-first FastAPI 프로젝트다.

현재 Phase 1 범위:

- v3alpha1 Pydantic 계약
- JSON Schema
- 계약 참조 무결성 검사
- 오류 envelope
- health·meta·capabilities API

아직 제공하지 않는 기능:

- URL·이미지 수집
- LLM 공고 구조화
- 사용자 적합도 실행
- 기술 그래프 연결
- 로드맵 생성

실행:

```powershell
cd C:\jobiss-service-ai-v3-lab\ai-v3
uv sync --dev
$env:JOBIS_AI_SHARED_SECRET="local-ai-v3-secret"
uv run uvicorn jobis_ai_v3.api:app --host 127.0.0.1 --port 8300
```

테스트:

```powershell
uv run pytest
```
