# 코퍼스 1,172건 시점 평가 자산 (2026-07-21 ~ 07-29)

2026-07-30에 Jobis_통합본_20260728 배치(6,918건)를 가산 적재하면서 코퍼스가
활성 1,172건 -> 약 6,900건으로 바뀌었다. 아래 산출물은 **바뀌기 전 코퍼스**에서 나온
값이며, 신규 코퍼스 결과와 **직접 비교할 수 없다**. 절대 수치를 비교하면 코퍼스 변화와
파이프라인 변화가 섞인다.

| 파일 | 내용 |
|---|---|
| `pool_spec.json` / `judgments_spec.json` / `report_spec.json` | 정규화 15질의 트랙 (439쌍 판정, 사람 118쌍 반영) |
| `pool_inputA.json` / `pool_inputB.json` / `judgments_input*.json` / `report_io_tracks.json` | 명세서 실입력 A/B 트랙 (골든 profile 12건) |
| `pool.json` / `judgments.json` / `report.json` | 자연어 30질의 트랙 (v5) |
| `ragas_*` | RAGAS 4축 (ID기반 2축 + 생성 2축, 프로덕션 생성 포함) |
| `dashboard_human*.html` | 사람 검증 반영 대시보드 |

## 보존해야 하는 이유

- `report_io_tracks.json`이 작업 3(질의 텍스트 구성 A/B)의 **근거 데이터**다.
  dense 입력B−입력A = −0.3030 [−0.492, −0.133]이 여기서 나왔다.
- 사람 손수 라벨 118쌍(`../../anchor/session_*.csv`)은 **여기 있는 (qid, uid) 조합**에
  묶여 있다. 신규 풀에서 다시 등장하는 쌍만 재사용 가능하며, 이전율은
  `../../judge_reliability.json`에 기록된다.
- `anchor/anchor_report_human.json`(게이트 3, κ=0.5921)은 이 시점 판정 결과 기준이다.

## 재현 불가

코퍼스 스냅샷 해시가 다르므로 이 산출물은 재실행으로 재현되지 않는다. 참조 전용.
