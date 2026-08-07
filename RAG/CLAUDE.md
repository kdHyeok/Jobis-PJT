# RAG 작업자 진입점

@AGENTS.md

루트 [../AGENTS.md](../AGENTS.md)가 상위 규약이다.

CI에서 고칠 파일은 [ci/test.sh](ci/test.sh)다. RAG는 `pyproject.toml`이 없어 CI 의존성이
그 파일에 고정 버전으로 직접 적혀 있으니, 새 패키지를 쓰면 함께 추가한다.
