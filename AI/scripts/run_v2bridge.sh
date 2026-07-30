#!/usr/bin/env bash
# v2bridge 서버 실행기 — push 자동 반영 포함.
#
# 사용:  AI/scripts/run_v2bridge.sh [포트]     (기본 8000)
#
# 하는 일:
#   1) uvicorn --reload 로 v2bridge 를 띄운다 (Windows 프로세스, uv 가 의존성 자동 설치).
#   2) 백그라운드 워처가 60초마다 원격을 확인해, 현재 브랜치에 새 커밋이 push 되면
#      fast-forward 로 코드를 갱신한다 → --reload 가 파일 변경을 감지해 서버가
#      즉시 최신 에이전트로 재기동된다 (병렬 개발 중 "push = 배포").
#
# 제약 (실측 2026-07-30):
#   · WSL git 은 lab.ssafy.com 인증이 안 된다 → fetch 는 메인 저장소(S15P11C202)에서
#     Windows git 으로 한다. worktree 는 메인 저장소와 refs 를 공유하므로 그걸로 충분하다.
#   · ff-merge 는 네트워크가 필요 없어 worktree 에서 WSL git 으로 한다.
#   · 작업 트리에 충돌하는 변경이 있거나 로컬 커밋이 분기했으면(ff 불가) 갱신을 건너뛰고
#     로그만 남긴다 — 서버를 위해 작업 중인 코드를 덮어쓰지 않는다.

set -u

PORT="${1:-8000}"
WORKTREE="/mnt/c/Users/SSAFY/Desktop/S15P11C202-ai"
AI_WIN='C:\Users\SSAFY\Desktop\S15P11C202-ai\AI'
MAIN_WIN='C:\Users\SSAFY\Desktop\S15P11C202'
UV_WIN='C:\Users\SSAFY\.local\bin\uv.exe'
INTERVAL="${PULL_INTERVAL_SEC:-60}"

BRANCH="$(git -C "$WORKTREE" branch --show-current)"
if [ -z "$BRANCH" ]; then
    echo "[v2bridge] 브랜치를 알 수 없어요 — detached HEAD 에서는 자동 갱신을 못 합니다" >&2
    exit 1
fi
echo "[v2bridge] 포트 $PORT, 브랜치 $BRANCH, ${INTERVAL}초 간격 자동 갱신"

watch_remote() {
    while true; do
        sleep "$INTERVAL"
        # 인증되는 쪽(메인 저장소, Windows git)으로 원격 refs 만 갱신한다.
        cmd.exe /c "cd /d $MAIN_WIN&& git fetch origin $BRANCH" >/dev/null 2>&1
        behind="$(git -C "$WORKTREE" rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null || echo 0)"
        [ "${behind:-0}" -gt 0 ] || continue
        if git -C "$WORKTREE" merge --ff-only "origin/$BRANCH" >/dev/null 2>&1; then
            echo "[v2bridge] origin/$BRANCH 의 새 커밋 ${behind}개 반영 — 서버가 자동 재기동됩니다"
        else
            echo "[v2bridge] 새 커밋 ${behind}개가 왔지만 fast-forward 불가(로컬 변경/분기) — 갱신 보류" >&2
        fi
    done
}

watch_remote &
WATCHER=$!
trap 'kill "$WATCHER" 2>/dev/null' EXIT

# 서버는 포그라운드 — 로그가 그대로 보이고 Ctrl+C 로 끝낸다.
# (exec 를 쓰면 EXIT trap 이 돌지 않아 워처가 고아로 남는다 — 일반 호출로 둔다.)
cmd.exe /c "cd /d $AI_WIN&& set PYTHONUTF8=1&& $UV_WIN run --with fastapi,uvicorn uvicorn jobis_ai.v2bridge.app:app --host 127.0.0.1 --port $PORT --reload --reload-dir src"
