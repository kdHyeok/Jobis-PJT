#!/usr/bin/env python3

from __future__ import annotations

import argparse

from codex_oauth_adapter.provider import CodexError, DEFAULT_MODEL, ask, login, logout, state_file


def main() -> int:
    parser = argparse.ArgumentParser(description="독립 OpenAI Codex OAuth 테스트")
    parser.add_argument("prompt", nargs="?")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--reasoning-effort",
        choices=["minimal", "low", "medium", "high", "xhigh", "max", "ultra"],
        default="medium",
    )
    parser.add_argument("--timeout", type=float)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--login", action="store_true")
    actions.add_argument("--logout", action="store_true")
    args = parser.parse_args()
    try:
        if args.login:
            login()
            print(f"로그인 완료: {state_file()}")
        elif args.logout:
            print("인증 정보를 삭제했습니다." if logout() else "삭제할 인증 정보가 없습니다.")
        else:
            prompt = args.prompt or input().strip()
            print(ask(prompt, args.model, args.reasoning_effort, args.timeout))
        return 0
    except CodexError as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
