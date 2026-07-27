# RAG/

RAG(Retrieval-Augmented Generation) 기능 개발을 격리해서 진행하는 디렉토리입니다.

## 현재 RAG 관련 자산 위치

RAG 관련 기존 코드와 문서는 AI 패키지 내부에 있습니다. 이 디렉토리로 분리·이관하기 전까지 아래 위치를 참고하세요.

| 자산 | 위치 |
|---|---|
| RAG 모듈 코드 | `AI/src/jobis_ai/rag.py` |
| RAG 어댑터 계약 문서 | `AI/docs/rag-adapter-contract.md` |
| RAG 팀 인터페이스 명세 | `AI/docs/rag-team-interface-spec.md` |
| RAG 테스트 | `AI/tests/test_nodes_and_rag.py` |

> `AI/src/jobis_ai/rag.py`는 AI 패키지의 import 경로에 묶여 있으므로, 코드 이관 시 AI 팀과 협의 후 진행합니다.
