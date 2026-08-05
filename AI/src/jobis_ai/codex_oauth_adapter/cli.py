"""JOBIS Codex OAuth 기기 로그인 CLI."""

from __future__ import annotations

import argparse

from jobis_ai.codex_oauth_adapter.provider import (
    CodexError,
    list_models,
    login,
    logout,
    state_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="JOBIS Codex OAuth 인증 관리")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--login", action="store_true")
    actions.add_argument("--logout", action="store_true")
    actions.add_argument("--models", action="store_true")
    args = parser.parse_args()
    try:
        if args.login:
            login()
            print(f"로그인 완료: {state_file()}")
        elif args.logout:
            print("인증 정보를 삭제했습니다." if logout() else "삭제할 인증 정보가 없습니다.")
        else:
            for model in list_models():
                print(model.get("slug") or model.get("id") or model)
        return 0
    except CodexError as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
