# Jobis: 잡코리아 IT 개발자 공고 수집

`crawl_jobkorea_it.py`는 잡코리아의 IT 개발 직무 공고 중 실제 상세 iframe에 `담당업무`, `자격요건`, `우대사항`이 모두 텍스트로 제공되는 공고만 수집합니다. 이미지 안에만 상세 정보가 있는 공고는 OCR을 사용하지 않고 제외합니다. `detail_text`에는 바깥 페이지의 요약이 아니라 이 상세 iframe 원문만 저장합니다.

별도 패키지 설치 없이 Python 3.11+에서 실행합니다.

```bash
python3 crawl_jobkorea_it.py --max-results 100
```

결과는 다음 위치에 생성됩니다.

- `data/job_postings/job_postings.db` — SQLite 데이터베이스
- `exports/job_postings.json` — 확인·활용하기 쉬운 JSON 파일

사람인 공고는 별도 수집기와 결과 파일을 사용합니다.

```bash
python3 crawl_saramin_it.py --max-results 100
```

- `data/saramin_job_postings/saramin_job_postings.db`
- `exports/saramin_job_postings.json`

수집 대상 사이트의 이용약관 및 robots.txt를 준수하고, 기본 요청 간격(`1.2`초)보다 짧게 설정하지 마세요.
