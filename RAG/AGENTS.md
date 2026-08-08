# RAG 작업 지침

루트 [AGENTS.md](../AGENTS.md)를 먼저 읽는다. 이 파일은 RAG에만 해당하는 규칙이다.

## CI에서 이 디렉토리가 책임지는 것

- **고칠 파일**: [ci/test.sh](ci/test.sh) — RAG에서 무엇을 검사하는가.
- **고치지 않을 파일**: 루트 `Jenkinsfile` — Python 이미지와 스테이지 배치는 뼈대가 책임진다.

현재 검사는 `compileall`(import·문법)과 `unittest discover -s RAG/tests`다.

## 의존성

RAG는 `pyproject.toml`을 두지 않으므로 CI 의존성이 `ci/test.sh`에 **고정 버전으로 직접**
적혀 있다. 새 패키지를 쓰기 시작했으면 그 파일에도 추가해야 CI가 돈다 — 로컬에서만
설치해 두고 넘어가면 CI에서 `ModuleNotFoundError`로 터진다.

버전을 올릴 때는 적재(`infra/airflow/Dockerfile.rag-ingest`)와 검색
(`infra/airflow/Dockerfile.rag-search`) 이미지도 함께 본다. 이 둘은 Infra 소유이므로
변경이 필요하면 MR + Infra 리뷰다.

## 벡터 공간 일관성

적재와 검색은 **같은 `RAG_EMBED_PROVIDER`, 같은 모델, 같은 `RAG_VECTOR_DIMENSIONS`** 를
써야 한다. 어긋나면 서로 다른 벡터 공간을 섞게 되므로 검색 서버가 기동을 거부한다.

- provider나 모델을 바꾸면 기존 벡터를 재사용하지 않고 **전량 재임베딩**이다.
  수천 청크를 외부 provider로 한 번에 올리면 키 한도와 과금을 빠르게 소진한다.
- 이 값을 바꾸는 변경은 비용이 발생하므로 MR 설명에 재임베딩 규모를 적는다.

## 기능을 추가·수정할 때

1. 검색·랭킹 로직을 바꿨으면 `RAG/tests`에 회귀 테스트를 같은 MR에 넣는다.
2. 평가 결과를 근거로 쓸 때는 총계뿐 아니라 케이스별 판정을 본다.
3. CI가 깨지면 원인을 만든 사람이 고친다.
