"""매일 새 채용공고를 증분 수집해 DB 적재용 SQL까지 한 번에 만든다(무인 실행용).

전체 흐름 — 앞 단계가 뒤 단계의 입력이므로 순서를 바꾸면 안 된다:

    1) 크롤링   5개 사이트에서 새 공고만 추가 (--max-new 로 상한)
    2) OCR      1)에서 need_ocr="O"로 분류된 공고의 이미지를 텍스트로 채움
    3) 합치기   사이트별 파일을 하나로 모으고 중복 제거
    4) SQL      운영 PostgreSQL 적재용 INSERT 문 생성

run_all_crawlers.py 는 크롤링과 합치기만 묶어주기 때문에, 그것만 돌리면 OCR을
건너뛴 채 병합돼 이미지형 공고의 본문이 빈 채로 통합본에 들어간다. 그래서 이
스크립트가 OCR을 사이에 끼워 넣은 전체 체인을 담당한다.

사람이 지켜보지 않는 자동 실행이 전제이므로 다음을 갖춘다:
  - 잠금 파일: 앞 실행이 안 끝났는데 또 시작하면 같은 JSON·DB를 동시에 써서
    파일이 깨진다. 이미 돌고 있으면 조용히 종료한다.
  - 로그 파일: 화면을 볼 수 없으므로 실행별 로그를 남기고 오래된 것은 지운다.
  - 부분 실패 허용: 한 사이트가 실패해도 나머지로 계속 진행한다(수집 자체가
    상대 사이트 상태에 좌우되므로, 하루 실패로 전체가 멈추면 안 된다).

실행:
    .venv/bin/python run_daily_update.py                 # 사이트당 새 공고 50건
    .venv/bin/python run_daily_update.py --max-new 100   # 상한 변경
    .venv/bin/python run_daily_update.py --skip-crawl    # 수집 없이 OCR~SQL만
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
LOCK_FILE = PROJECT_ROOT / "logs" / ".daily_update.lock"
SITES = ("jobkorea", "saramin", "wanted", "incruit", "work24")

# 잠금 파일이 남아 있어도 이 시간이 지났으면 죽은 실행으로 보고 무시한다.
# (전원이 갑자기 꺼지면 잠금을 지우지 못한 채 종료되어 영구히 막힐 수 있다.)
STALE_LOCK_HOURS = 6
LOG_RETENTION_DAYS = 14


class Logger:
    """화면과 로그 파일에 동시에 기록한다(자동 실행 뒤 원인 추적용)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a", encoding="utf-8")

    def write(self, message: str) -> None:
        stamped = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        print(stamped, flush=True)
        self.file.write(stamped + "\n")
        self.file.flush()

    def close(self) -> None:
        self.file.close()


def acquire_lock(log: Logger) -> bool:
    """중복 실행을 막는다. 이미 실행 중이면 False."""
    if LOCK_FILE.exists():
        age_hours = (time.time() - LOCK_FILE.stat().st_mtime) / 3600
        if age_hours < STALE_LOCK_HOURS:
            pid = LOCK_FILE.read_text(encoding="utf-8").strip()
            log.write(
                f"status=already_running pid={pid} age_hours={age_hours:.1f} "
                "— 이번 실행은 건너뜁니다."
            )
            return False
        log.write(
            f"status=stale_lock_removed age_hours={age_hours:.1f} "
            "— 비정상 종료로 남은 잠금이라 무시합니다."
        )
        LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def run_step(log: Logger, name: str, command: list[str]) -> bool:
    """한 단계를 실행하고 성공 여부를 돌려준다. 출력은 로그에 함께 남긴다."""
    log.write(f"step={name} status=started")
    started = time.time()

    # 자식 출력을 받는 즉시 로그에 흘려보낸다. subprocess.run(stdout=PIPE)로 한 번에
    # 모아서 쓰면 크롤링·OCR처럼 몇 분 걸리는 단계 동안 로그 파일이 전혀 늘지 않아
    # `tail -f`로 진행 상황을 볼 수 없고, 살아 있는지 멈췄는지 구분도 안 된다.
    summary = ""
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,  # 줄 단위 버퍼링
    )
    with process.stdout as stream:
        for raw in stream:
            line = raw.rstrip()
            log.file.write(f"    {line}\n")
            log.file.flush()
            if "status=completed" in line:
                summary = line  # 각 스크립트가 마지막에 찍는 요약을 계속 갱신해 둔다.
    returncode = process.wait()
    elapsed = time.time() - started

    if summary:
        log.write(f"    {summary}")
    if returncode:
        log.write(f"step={name} status=failed exit_code={returncode} 소요={elapsed:.0f}초")
        return False
    log.write(f"step={name} status=completed 소요={elapsed:.0f}초")
    return True


def cleanup_logs(log: Logger) -> None:
    """오래된 로그를 지운다(무인 실행이라 방치하면 계속 쌓인다)."""
    cutoff = time.time() - LOG_RETENTION_DAYS * 86400
    removed = 0
    for path in LOG_DIR.glob("daily_update_*.log"):
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    if removed:
        log.write(f"status=logs_cleaned removed={removed} keep_days={LOG_RETENTION_DAYS}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-new",
        type=int,
        default=50,
        help="사이트당 이번 실행에서 새로 추가할 공고 수 상한 (기본값: 50)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="HTTP 요청 사이 대기 시간(초). 사이트에 부담을 주지 않도록 0.5 이상",
    )
    parser.add_argument(
        "--max-ocr-pending-results",
        type=int,
        default=200,
        help="사이트당 새로 받아둘 이미지형(OCR 대기) 공고 상한 (기본값: 200)",
    )
    parser.add_argument("--skip-crawl", action="store_true", help="수집을 건너뛰고 OCR~SQL만 실행")
    parser.add_argument("--skip-ocr", action="store_true", help="OCR을 건너뜀")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_new < 1 or args.delay < 0.5 or args.max_ocr_pending_results < 0:
        raise SystemExit("--max-new는 1 이상, --delay는 0.5 이상이어야 합니다.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = Logger(LOG_DIR / f"daily_update_{stamp}.log")
    log.write(f"status=started max_new={args.max_new} python={sys.executable}")

    if not acquire_lock(log):
        log.close()
        return 0  # 중복 실행은 오류가 아니므로 정상 종료로 알린다.

    failures: list[str] = []
    try:
        # 1) 크롤링 — 사이트별로 --max-new 만큼만 새로 추가한다(이미 있는 공고는 건너뜀).
        #    run_all_crawlers.py 는 끝에 merge까지 하지만, 여기서는 OCR 뒤에 다시
        #    merge하므로 그 결과는 어차피 3)에서 덮어써진다.
        if not args.skip_crawl:
            ok = run_step(log, "crawl", [
                sys.executable, str(PROJECT_ROOT / "run_all_crawlers.py"),
                "--max-results", "100000",   # 증분 수집에서는 --max-new 가 실질 상한
                "--max-ocr-pending-results", str(args.max_ocr_pending_results),
                "--max-new", str(args.max_new),
                "--delay", str(args.delay),
                "--pages-per-keyword", "2",
            ])
            if not ok:
                # 일부 사이트 실패는 run_all_crawlers 가 exit 1로 알린다. 수집분이
                # 남아 있으므로 뒤 단계를 계속 진행한다.
                failures.append("crawl")

        # 2) OCR — 사이트별로 따로 돌린다. 한 사이트가 죽어도 나머지는 계속.
        if not args.skip_ocr:
            for site in SITES:
                if not run_step(log, f"ocr:{site}", [
                    sys.executable, str(PROJECT_ROOT / "enrich_ocr.py"),
                    "--site", site, "--in-place",
                ]):
                    failures.append(f"ocr:{site}")

        # 3) 합치기 — 여기서 실패하면 통합본이 갱신되지 않으므로 4)도 의미가 없다.
        if not run_step(log, "merge", [sys.executable, str(PROJECT_ROOT / "merge_job_postings.py")]):
            failures.append("merge")
            log.write("status=aborted reason=merge_failed — 통합본이 갱신되지 않아 SQL 생성을 건너뜁니다.")
            return 1

        # 4) SQL — 운영 DB 적재용. ON CONFLICT DO NOTHING 이라 여러 번 넣어도 안전하다.
        if not run_step(log, "export_sql", [sys.executable, str(PROJECT_ROOT / "export_postgres.py")]):
            failures.append("export_sql")

        cleanup_logs(log)
    finally:
        LOCK_FILE.unlink(missing_ok=True)

    if failures:
        log.write(f"status=completed_with_failures steps={','.join(failures)}")
        log.close()
        return 1
    log.write("status=completed 모든 단계 성공")
    log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
