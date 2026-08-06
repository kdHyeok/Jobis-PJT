from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request


HOST = "127.0.0.1"
PORT = 18300
BASE_URL = f"http://{HOST}:{PORT}"
SECRET = "smoke-ai-secret-123"


def request(
    path: str,
    *,
    authenticated: bool = False,
    payload: dict | None = None,
) -> tuple[int, dict]:
    headers = {}
    if authenticated:
        headers = {
            "X-JOBIS-AI-SECRET": SECRET,
            "X-JOBIS-AI-CONTRACT": "jobis.ai.v3alpha1",
        }
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(
        urllib.request.Request(BASE_URL + path, headers=headers, data=data),
        timeout=2,
    ) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main() -> int:
    environment = os.environ.copy()
    environment.update(
        {
            "JOBIS_ENV": "local",
            "JOBIS_AI_SHARED_SECRET": SECRET,
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "jobis_ai_v3.api:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--log-level",
            "warning",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        for _ in range(50):
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout is not None else ""
                raise RuntimeError(f"server exited before health check:\n{output}")
            try:
                status, health = request("/health")
                if status == 200 and health.get("status") == "UP":
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not become healthy within 5 seconds")

        meta_status, meta = request("/v1/meta", authenticated=True)
        if meta_status != 200 or meta.get("contractVersion") != "jobis.ai.v3alpha1":
            raise RuntimeError(f"unexpected meta response: {meta}")

        source_status, source = request(
            "/v1/sources/acquire",
            authenticated=True,
            payload={
                "inputType": "TEXT",
                "entryPoint": "CHAT",
                "text": "백엔드 개발자 채용\n지원 자격: 신입\nJava 경험 필수",
            },
        )
        if source_status != 200 or source.get("status") != "AWAITING_VERIFICATION":
            raise RuntimeError(f"unexpected source response: {source}")
        verify_status, verified = request(
            f"/v1/sources/{source['sourceDocumentId']}/verify",
            authenticated=True,
            payload={
                "sourceDocument": source,
                "verifiedText": source["rawText"],
                "corrections": [],
                "verifiedBy": "USER",
            },
        )
        if verify_status != 200 or verified["sourceDocument"].get("status") != "VERIFIED":
            raise RuntimeError(f"unexpected verification response: {verified}")
        print(
            "server smoke passed: health=UP, contract=jobis.ai.v3alpha1, "
            "source=AWAITING_VERIFICATION->VERIFIED"
        )
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
