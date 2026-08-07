#!/usr/bin/env bash
# RAG CI — RAG 개발자 소유.
#
# 호출: Jenkinsfile 'RAG: static validation' 스테이지가 workspace 루트에서
#       `bash RAG/ci/test.sh` 로 실행한다. Python 이미지는 Jenkinsfile이 고른다.
#
# RAG 는 pyproject 를 두지 않으므로 의존성을 여기에 고정 버전으로 적는다.
# 버전을 올리면 적재(rag-ingest)와 검색(rag-search) 이미지의 버전도 함께 본다 —
# 임베딩 provider·모델·차원이 어긋나면 서로 다른 벡터 공간을 섞게 된다.
set -euo pipefail

venv=/tmp/jobis-rag-venv
python -m venv "$venv"
"$venv/bin/python" -m pip install \
  --disable-pip-version-check --no-cache-dir \
  numpy==2.2.6 rank_bm25==0.2.2 \
  'psycopg[binary]==3.2.9' python-dotenv==1.1.1

cd "$(dirname "$0")/../.."

"$venv/bin/python" -m compileall -q RAG
"$venv/bin/python" -m unittest discover -s RAG/tests -v
