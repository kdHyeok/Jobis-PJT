# Jobis: IT 개발자 채용공고 수집

5개 채용 사이트(잡코리아·사람인·원티드·인크루트·고용24)에서 **IT 개발 직무 공고**를
수집한다. 상세 본문에 **담당업무·자격요건이 텍스트로 제공되는 공고**(`need_ocr="X"`)를
기본 수집 대상으로 하고, **이미지 안에만 내용이 있는 공고**(`need_ocr="O"`)는 이미지 URL만
따로 모아 OCR로 본문을 채운다. `detail_text`에는 요약이 아니라 실제 상세 원문만 저장한다.

## 파이프라인 4단계

```
① 크롤링    crawl_*.py            5개 사이트에서 공고 수집
② OCR       enrich_ocr.py         need_ocr="O" 공고의 이미지 → 텍스트
③ 합치기    merge_job_postings.py 사이트별 결과 통합 + 중복 제거
④ SQL       export_postgres.py    운영 PostgreSQL 적재용 INSERT 생성
```

**②를 ③보다 먼저 돌려야 한다.** OCR이 사이트별 파일의 `detail_text`를 채운 뒤에 합쳐야
하므로, 순서를 바꾸면 이미지형 공고가 본문 없이 통합본에 들어간다.

네 단계를 한 번에 돌리려면 **`run_daily_update.py`** 를 쓴다(아래 "자동 실행" 참고).

크롤링·통합·SQL은 표준 라이브러리만 쓰고, OCR만 별도 패키지가 필요하다.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 핵심: 중단돼도 이어서 모은다 (resume 기본)

대량 수집은 오래 걸려서 중간에 끊기기 쉽다. 그래서 모든 크롤러가 다음을 지원한다.

- **중간 저장(checkpoint)**: `--checkpoint-every N`(기본 25)마다 JSON·DB에 저장한다.
  실행이 끊겨도 그때까지 모은 공고는 남는다.
- **이어서 수집(resume)이 기본**: 다시 실행하면 기존 결과 JSON을 읽어 **이미 저장한 공고는
  건너뛰고** 목표 수를 채울 때까지 이어서 모은다. 처음부터 다시 모으려면 `--fresh`를 준다.
- **스트리밍**: 검색 결과를 발견하는 즉시 상세를 수집하므로, 목표 수에 도달하면 곧바로 멈춘다.

## ① 사이트별 대량 수집 (처음 모을 때)

각 명령은 **텍스트 공고 2,000건**을 목표로 하고, **이미지형(OCR 대기) 공고는 별도로 500건**까지
함께 모은다. 중간에 끊기면 **같은 명령을 다시 실행**하면 이어서 채운다.

```bash
# 잡코리아 (깊은 페이지까지 됨 → pages-per-keyword 크게)
python3 crawl_jobkorea_it.py --max-results 2000 --max-ocr-pending-results 500 --pages-per-keyword 40 --delay 1.2

# 사람인
python3 crawl_saramin_it.py  --max-results 2000 --max-ocr-pending-results 500 --pages-per-keyword 40 --delay 1.2

# 원티드 (검색 API가 쿼리당 ~700건까지만 → 페이지보다 검색어 수가 관건. pages는 35면 충분)
python3 crawl_wanted_it.py   --max-results 2000 --max-ocr-pending-results 500 --pages-per-keyword 35 --delay 1.2

# 인크루트 (한 페이지 30건)
python3 crawl_incruit_it.py  --max-results 2000 --max-ocr-pending-results 500 --pages-per-keyword 40 --delay 1.2

# 고용24 (한 페이지 10건 → pages-per-keyword 더 크게)
python3 crawl_work24_it.py   --max-results 2000 --max-ocr-pending-results 500 --pages-per-keyword 120 --delay 1.2
```

- `--max-results`는 **텍스트 공고** 상한, `--max-ocr-pending-results`는 **이미지형 공고** 상한이다(서로 별개).
- 두 상한을 모두 채우거나 검색 결과가 소진되면 멈춘다. 목표에 못 미치면 `--pages-per-keyword`를 더 키운다.
- `--delay`는 사이트 정책을 지키기 위한 요청 간격이다. **1.2초보다 짧게 설정하지 말 것.**

### 결과 위치

| 사이트 | SQLite | JSON |
|---|---|---|
| 잡코리아 | `data/jobkorea_job_postings/jobkorea_job_postings.db` | `exports/jobkorea_job_postings.json` |
| 사람인 | `data/saramin_job_postings/saramin_job_postings.db` | `exports/saramin_job_postings.json` |
| 원티드 | `data/wanted_job_postings/wanted_job_postings.db` | `exports/wanted_job_postings.json` |
| 인크루트 | `data/incruit_job_postings/incruit_job_postings.db` | `exports/incruit_job_postings.json` |
| 고용24 | `data/work24_job_postings/work24_job_postings.db` | `exports/work24_job_postings.json` |

## ② 이미지형 공고 OCR 보강

`need_ocr="O"` 로 분류된 공고의 이미지를 읽어 `detail_text`를 채운다. 로컬 PaddleOCR을
쓰므로 외부 API 비용이 없다.

```bash
.venv/bin/python enrich_ocr.py --site jobkorea --in-place
```

- `--in-place` 없이 실행하면 원본을 건드리지 않고 `*_ocr.json` 으로 따로 저장한다.
- **해당 사이트 크롤러가 실행 중이면 쓰지 말 것.** 같은 JSON·DB를 동시에 쓰면 깨진다.
- 채택 기준: 공백 제외 **250자 이상** + 채용 신호어 3개 이상. 로고·장식 이미지처럼 글자가
  거의 없는 결과는 자동으로 걸러진다.
- 실패한 공고는 `exports/<사이트>_job_postings_ocr_failed.json` 에 기록되어 다음 실행에서
  건너뛴다. 다시 시도하려면 `--retry-failed` 를 준다.

## ③ 전체를 하나로 합치기 (중복 제거)

**같은 회사의 같은 공고명**을 사이트 간 중복으로 보고, 텍스트 상세·메타데이터가 더 풍부한
쪽을 남긴다.

```bash
python3 merge_job_postings.py
```

- 결과: `data/all_job_postings/all_job_postings.db`, `exports/all_job_postings.json`
- **아직 수집하지 않은 사이트가 있어도** 있는 사이트만으로 병합한다.
- **본문이 빈 공고는 통합본에 넣지 않는다.** OCR로도 못 채운 공고를 공고 ID로만
  막으면, 같은 회사가 같은 공고를 새 ID로 다시 올릴 때 그대로 들어온다. 통합 단계에서
  본문 유무로 한 번 더 거른다(로그의 `empty_body_dropped`). 원본 사이트별 JSON은
  그대로 두므로, 나중에 OCR이 성공하면 다음 통합 때 자연히 포함된다.
- **`deadline_date` 를 여기서 만든다.** 마감일 표기가 사이트마다 달라(`2026.08.26`,
  `2026-08-26T23:59`, `2026년 08월 21일`, `2026년 07월 01일 ~ 2026년 07월 31일`,
  `상시채용` …) 쓰는 쪽이 각자 파싱하면 팀마다 다른 버그가 생긴다. 통합 단계에서 한 번만
  파싱해 `YYYY-MM-DD` 로 통일한다(날짜가 없으면 `null`).

## ④ 운영 DB 적재용 SQL 생성

```bash
python3 export_postgres.py
```

- 결과: `exports/all_job_postings_postgres.sql`
- `ON CONFLICT DO NOTHING` 이라 **같은 파일을 여러 번 실행해도 안전**하다.
- `text_source` 컬럼으로 본문 출처를 구분한다: `original`(사이트 원문) / `ocr`(이미지 추출).
- `deadline_date` 는 원본 마감일 문자열에서 파싱한 `DATE` 값이다(비교·정렬용).

## 자동 실행 (일일 증분 수집)

네 단계를 한 번에 돌린다. 사이트당 새 공고를 `--max-new` 만큼만 추가하므로 매일 돌려도
부담이 없다.

```bash
.venv/bin/python run_daily_update.py                 # 사이트당 새 공고 50건(기본)
.venv/bin/python run_daily_update.py --max-new 100
.venv/bin/python run_daily_update.py --skip-crawl    # 수집 없이 OCR~SQL만 다시
```

무인 실행을 전제로 다음을 갖추고 있다.

- **중복 실행 방지**: 앞 실행이 안 끝났는데 또 시작하면 같은 파일을 동시에 써서 깨진다.
  이미 돌고 있으면 조용히 종료한다(비정상 종료로 남은 잠금은 6시간 뒤 자동 무시).
- **실행별 로그**: `logs/daily_update_<시각>.log` (14일 후 자동 삭제). 자식 프로세스 출력을
  받는 즉시 기록하므로 `tail -f` 로 진행 상황을 실시간으로 볼 수 있다.
- **부분 실패 허용**: 한 사이트가 실패해도 나머지로 계속 진행한다.

Windows 작업 스케줄러 등록 방법은 [자동화_설정방법.md](자동화_설정방법.md) 참고.

## 재수집 제외 목록

사람이 직접 확인해 **"본문을 채울 방법이 없다"고 판정한 공고**는 데이터에서 지워도 사이트에
그대로 살아 있어서, 그냥 두면 다음 수집에서 새 공고로 다시 들어온다. 그러면 본문이 빈
레코드가 매일 되살아난다. 그래서 제외 판정을 `exports/excluded_postings.json` 에 남기고
5개 크롤러가 이를 "이미 아는 공고"와 같이 취급해 건너뛴다.

```json
{ "잡코리아": ["49294518", ...], "사람인": [...] }
```

제외 대상 예시 — 이미지가 사이트 자동 삽입 장식(카테고리 아이콘, `blank.png`)뿐인 공고,
마케팅 배너만 있는 공고, 채용공고가 아닌 교육과정 모집, 본문 텍스트가 없는 공고.

## 수집 결과 확인

특정 날짜에 무엇이 새로 들어왔는지 조회한다(조회 전용이라 수집 중에 실행해도 안전).

```bash
python3 report_collection.py               # 오늘(한국 시간) 수집분
python3 report_collection.py --list        # 공고 제목 전부 나열
python3 report_collection.py --days 7      # 최근 7일
```

사이트별 신규·누적 건수, 본문 출처(원문/OCR), 신규 공고의 기술 키워드 분포를 보여준다.

> `collected_at` 은 UTC로 저장된다. 한국 시간 오전 수집분은 UTC로 전날 23시라, 날짜
> 문자열만 잘라 비교하면 오늘 수집분을 통째로 놓친다. 이 스크립트는 KST로 변환해 비교한다.

## 수집 필드 (공통 스키마)

**사이트별 파일** (크롤러가 저장하는 원본)

`source, posting_id, company, title, url, employment_type, experience, education,
location, posted_date, deadline, detail_text, image_urls, need_ocr, collected_at`

**통합본** (`all_job_postings.json`) — 위 필드에 `deadline_date` 추가

| 필드 | 설명 |
|---|---|
| `deadline` | 사이트가 준 원본 표기 그대로 (화면 표시용) |
| `deadline_date` | `YYYY-MM-DD` 로 통일한 마감일. 날짜가 없으면(상시채용 등) `null` |

마감 여부는 **저장하지 않는다.** 저장하는 순간 낡기 때문(오늘 유효해도 내일 마감).
쓰는 쪽이 조회 시점에 오늘 날짜와 비교한다.

```python
# 지원 가능한 공고 (마감일 없는 상시채용 포함)
active = [p for p in postings
          if p["deadline_date"] is None or p["deadline_date"] >= date.today().isoformat()]
```

- `need_ocr`: `"X"` = 본문 저장 완료, `"O"` = 이미지형(이미지 URL만 저장, OCR 대기)
- 텍스트 공고 판정: **담당업무 + 자격요건**이 본문에 있고 300자 이상이면 저장
  (우대사항은 있으면 함께 저장, 필수는 아님).
- 라벨이 없어 위 기준을 못 넘겨도 이미지가 있으면 OCR 대기로 보존한다.

---

수집 대상 사이트의 이용약관과 robots.txt를 준수하고, 기본 요청 간격(`1.2`초)보다 짧게 설정하지 말 것.
