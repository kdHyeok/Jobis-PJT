# DATA/

채용공고 데이터 수집(크롤러·수집 데이터) 디렉토리입니다.

## 작업 규칙

새 작업은 `feat/data/<기능명>` 브랜치를 develop에서 분기해 진행합니다.

## 구성

| 파일 | 역할 |
|---|---|
| `crawl_jobkorea_it.py` | 잡코리아 크롤러 (공통 검색어·필터·유틸의 허브 — 다른 크롤러가 import) |
| `crawl_saramin_it.py` | 사람인 크롤러 |
| `crawl_wanted_it.py` | 원티드 크롤러 (공식 검색 API 사용) |
| `crawl_incruit_it.py` | 인크루트 크롤러 |
| `crawl_work24_it.py` | 고용24 크롤러 |
| `run_all_crawlers.py` | 5개 크롤러 순차 실행 + 자동 병합 (일일 증분 수집용 `--max-new` 지원) |
| `merge_job_postings.py` | 사이트 간 중복 제거 통합 (회사명+공고명 기준) |
| `enrich_ocr.py` | 이미지형 공고 OCR 보강 (PaddleOCR, 로컬·무료) |
| `crawl_developer_reviews.py` | 개발자 합격 후기 수집 (Selenium) |
| `build_agent_reference_data.py` | 통합 공고+후기 → 로드맵 에이전트용 참조 JSON |
| `데이터수집_방법론.md` | 수집 기준·사이트별 방식·한계 문서 (발표/공유용) |

크롤러 5종은 **표준 라이브러리만** 사용합니다(Python 3.11+). OCR은 `paddlepaddle paddleocr`,
후기 수집은 `selenium` 설치가 필요합니다(`requirements.txt` 참고).

## 사용법 (사이트별 1,500~2,000건 수집)

각 크롤러는 **중단돼도 같은 명령으로 재실행하면 이어서 수집**합니다(25건마다 자동 저장).
`--max-results`는 텍스트 공고, `--max-ocr-pending-results`는 이미지형(OCR 대기) 공고의 상한이며
서로 별개로 카운트됩니다.

```bash
python3 crawl_jobkorea_it.py --max-results 2000 --max-ocr-pending-results 500 --pages-per-keyword 40 --delay 1.2
python3 crawl_saramin_it.py  --max-results 2000 --max-ocr-pending-results 500 --pages-per-keyword 40 --delay 1.2
python3 crawl_wanted_it.py   --max-results 2000 --max-ocr-pending-results 500 --pages-per-keyword 35 --delay 1.2
python3 crawl_incruit_it.py  --max-results 2000 --max-ocr-pending-results 500 --pages-per-keyword 40 --delay 1.2
python3 crawl_work24_it.py   --max-results 2000 --max-ocr-pending-results 500 --pages-per-keyword 120 --delay 1.2
```

전부 끝나면 통합(중복 제거):

```bash
python3 merge_job_postings.py
```

결과 위치: `data/<사이트>_job_postings/*.db`(SQLite) + `exports/<사이트>_job_postings.json`,
통합본은 `data/all_job_postings/` + `exports/all_job_postings.json`.

## 일일 증분 업데이트

`--max-new N` = 이번 실행에서 **새 공고 N건만** 추가하고 종료. 전 사이트 최신 등록순이라
앞 페이지만 훑으면 되므로 10~20분 안에 끝납니다.

```bash
python3 run_all_crawlers.py --max-results 99999 --max-ocr-pending-results 9999 --max-new 100 --pages-per-keyword 5 --delay 1.2
```

⚠️ `--max-results`는 누적 총량 상한이므로 증분 수집 시 위처럼 크게 지정해야 합니다.

## 이미지형 공고 OCR 보강

본문이 이미지뿐인 공고(`need_ocr="O"`)의 이미지를 OCR로 읽어 본문을 채웁니다.
검증: 실측 CER 9.4% (정확도 90.6%), 기술 키워드 보존율 100%. 상세는 방법론 문서 4장.

```bash
# 해당 사이트 크롤러 종료 후에만 실행 (원본 JSON/DB 직접 갱신)
python3 enrich_ocr.py --site jobkorea --in-place
```

## 수집 데이터 관리

수집 결과물(`data/`, `exports/`)은 용량 문제로 git에 포함하지 않습니다(`.gitignore` 처리).
데이터 전달 방식은 팀 협의로 결정합니다.

자세한 수집 기준·사이트별 구현 방식·한계는 [데이터수집_방법론.md](데이터수집_방법론.md) 참고.
