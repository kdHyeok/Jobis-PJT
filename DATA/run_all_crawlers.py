"""5개 채용 사이트 크롤러를 한 번에 순서대로 실행한다.

기본 실행은 사이트별 텍스트 공고 최대 10개를 JSON과 SQLite에 저장한다.
각 크롤러는 독립적으로 실행되므로 한 사이트에서 실패해도 나머지 사이트의
수집은 계속된다.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
CRAWLERS = (
    ("jobkorea", "crawl_jobkorea_it.py", ()),
    ("saramin", "crawl_saramin_it.py", ()),
    ("wanted", "crawl_wanted_it.py", ()),
    ("incruit", "crawl_incruit_it.py", ("--pages-per-keyword", "1")),
    ("work24", "crawl_work24_it.py", ("--pages-per-keyword", "1")),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="사이트별 텍스트 공고 최대 수 (기본값: 10)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="각 크롤러의 HTTP 요청 사이 대기 시간(초) (기본값: 1.0)",
    )
    parser.add_argument(
        "--max-ocr-pending-results",
        type=int,
        default=0,
        help="사이트별 이미지형(OCR 대기) 공고 최대 수 (기본값: 0)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_results < 1 or args.delay < 0.5 or args.max_ocr_pending_results < 0:
        raise SystemExit("--max-results는 1 이상, --delay는 0.5 이상이어야 합니다.")

    failures: list[str] = []
    for source, script_name, extra_args in CRAWLERS:
        command = [
            sys.executable,
            str(PROJECT_ROOT / script_name),
            "--max-results",
            str(args.max_results),
            "--delay",
            str(args.delay),
            "--max-ocr-pending-results",
            str(args.max_ocr_pending_results),
            *extra_args,
        ]
        print(f"[run_all] source={source} status=started", flush=True)
        result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        if result.returncode:
            failures.append(source)
            print(
                f"[run_all] source={source} status=failed "
                f"exit_code={result.returncode}",
                flush=True,
            )
        else:
            print(f"[run_all] source={source} status=completed exit_code=0", flush=True)

    if failures:
        print(f"[run_all] status=completed_with_failures sources={','.join(failures)}", flush=True)
        return 1
    print("[run_all] source=all_job_postings status=started", flush=True)
    merge_result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "merge_job_postings.py")],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if merge_result.returncode:
        print(
            f"[run_all] source=all_job_postings status=failed "
            f"exit_code={merge_result.returncode}",
            flush=True,
        )
        return merge_result.returncode
    print("[run_all] source=all_job_postings status=completed exit_code=0", flush=True)
    print("[run_all] status=completed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
