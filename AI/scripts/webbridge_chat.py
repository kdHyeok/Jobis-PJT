"""웹 브릿지와 직접 대화하는 개발용 클라이언트.

브라우저·백엔드·MySQL 없이 브릿지(webbridge)만 띄워 놓고 대화를 돌려볼 때 쓴다.
웹백엔드(FakeAgentClient)와 **똑같은 WS 계약**으로 말하므로, 여기서 보이는 메시지가
브라우저에 중계되는 것과 같다. 즉 여기서 이상하면 웹에서도 이상하다.

사용:
    # 브릿지를 먼저 띄운다 (다른 터미널)
    uv run uvicorn jobis_ai.webbridge.app:app --port 8100

    # 샘플 공고로 대화
    uv run python AI/scripts/webbridge_chat.py --url ws://127.0.0.1:8100/

    # 내 공고·자료로 대화
    uv run python AI/scripts/webbridge_chat.py --posting 공고.txt --evidence 자료.txt

자료 파일(--evidence) 형식 — 한 줄에 하나, `종류|이름|설명`:
    STACK|Java|
    PROJECT|팀 게시판|Spring Boot + JPA, N+1 개선
    EDU|한국대 컴퓨터공학과|학사 졸업
종류는 웹 DB 의 EvidenceKind: PROJECT · GITHUB · PORTFOLIO · STACK · EDU · CERT
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from websockets.sync.client import connect

SAMPLE_POSTING = """[클라우드웨이브] 백엔드 엔지니어 (경력 3년 이상)

주요 업무
- Java/Spring Boot 기반 백엔드 API 개발 및 운영
- MySQL 데이터베이스 설계 및 쿼리 최적화
- AWS 환경에서의 서비스 배포 및 운영

자격 요건
- 경력 3년 이상 (신입 불가)
- Java, Spring Boot 실무 개발 경험
- RDBMS(MySQL) 설계 및 SQL 작성 능력
- Git 기반 협업 경험

우대 사항
- 대용량 트래픽 처리 및 성능 개선 경험
- Docker, Kubernetes 등 컨테이너 환경 경험
- 정보처리기사 자격증
"""

SAMPLE_EVIDENCES = [
    {"kind": "STACK", "label": "Java", "description": ""},
    {"kind": "STACK", "label": "Spring Boot", "description": ""},
    {"kind": "STACK", "label": "MySQL", "description": ""},
    {"kind": "STACK", "label": "Git", "description": ""},
    {"kind": "PROJECT", "label": "팀 게시판 프로젝트",
     "description": "Spring Boot 3 + JPA 로 게시판 REST API 구현. 목록 조회 N+1 문제를 "
                    "fetch join 으로 개선. 팀 4명, 2024.03~2024.06, 백엔드 담당."},
    {"kind": "EDU", "label": "한국대학교 컴퓨터공학과", "description": "학사 졸업 · 2020.03~2024.02"},
]

# 터미널 색 — 누가 말하는지 구분되게. 색을 지원하지 않는 터미널이면 --no-color.
DIM, BOLD, CYAN, GREEN, YELLOW, RED, RESET = (
    "\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


def parse_evidences(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        rows.append({
            "kind": (parts[0] or "PROJECT").upper(),
            "label": parts[1] if len(parts) > 1 else "",
            "description": parts[2] if len(parts) > 2 else "",
        })
    return rows


def print_report(result: dict, c: dict) -> None:
    """DONE.result — 브라우저가 리포트로 그리는 내용을 그대로 글로 보여준다."""

    rd = result.get("readiness") or {}
    dec = result.get("decision") or {}
    print(f"\n{c['BOLD']}━━ 리포트 (웹이 DB에 저장하고 화면에 그리는 내용) ━━{c['RESET']}")
    print(f"  적합도  {rd.get('now')}/100 → 로드맵 완주 시 {rd.get('goal')}")
    print(f"  판정    {rd.get('judge')}")
    print(f"  최대격차 {rd.get('topGap')} · {rd.get('topGapFix')}")
    print(f"\n  {c['BOLD']}목표 상태{c['RESET']} [{dec.get('status')}] {dec.get('label')}")
    print(f"    {dec.get('headline')}")
    for r in dec.get("reasons") or []:
        print(f"    - {r}")
    for h in dec.get("hardConstraints") or []:
        print(f"    ⚠ {h.get('requirement')} (현재: {h.get('current')})")

    print(f"\n  {c['BOLD']}요건 대조{c['RESET']}")
    sym = {"ok": "✓", "no": "✕", "tri": "△"}
    for g in result.get("gaps") or []:
        print(f"    {sym.get(g['mark'], '·')} {g['requirement']}")
        print(f"        {g.get('fix') or g.get('evidence') or ''}")

    print(f"\n  {c['BOLD']}준비 로드맵{c['RESET']}")
    for s in result.get("roadmap") or []:
        print(f"    {s['no']} [{s['status']}] {s['title']}  {s.get('delta') or ''}")
        print(f"        {s.get('meta') or ''} · {s.get('state') or ''}")
        if s.get("tags"):
            print(f"        겨냥: {', '.join(s['tags'])}")

    print(f"\n  {c['BOLD']}지원 경로{c['RESET']}")
    for rt in result.get("routes") or []:
        risk = " ⚠필수조건 충돌" if rt.get("hardRisk") else ""
        print(f"    [{rt['id']}] {rt['title']} · 준비부담 {rt['effort']}{risk}")
        print(f"        {rt.get('summary') or ''}")

    alts = result.get("alternatives") or []
    print(f"\n  {c['BOLD']}대체 공고{c['RESET']} {len(alts)}건")
    for a in alts:
        print(f"    [{a.get('label')}] {a.get('company')} / {a.get('role')} — {a.get('reason')}")
    sugg = (result.get("trace") or {}).get("alternativeSuggestions") or []
    if sugg:
        print(f"    {c['DIM']}(출처 공고가 없어 카드로 못 낸 제안 {len(sugg)}건 — RAG 미연결){c['RESET']}")

    warns = (result.get("trace") or {}).get("warnings") or []
    if warns:
        print(f"\n  {c['DIM']}판정 경고{c['RESET']}")
        for w in warns:
            print(f"    {c['DIM']}· [{w.get('node','')}/{w.get('code','')}] {w.get('message','')}{c['RESET']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="웹 브릿지와 직접 대화 (개발용)")
    ap.add_argument("--url", default="ws://127.0.0.1:8100/", help="브릿지 WS 주소")
    ap.add_argument("--posting", help="공고 원문 파일 (없으면 샘플 공고)")
    ap.add_argument("--evidence", help="자료 파일 (종류|이름|설명, 없으면 샘플 자료)")
    ap.add_argument("--company", default="", help="공고의 회사명 (웹이 아는 값이 있을 때)")
    ap.add_argument("--role", default="", help="공고의 직무명")
    ap.add_argument("--career", default="", help="공고의 경력 조건 문구")
    ap.add_argument("--no-evidence", action="store_true",
                    help="자료 없이 시작 — 에이전트가 대화 중에 이력서를 요청하는 흐름 확인용")
    ap.add_argument("--json", action="store_true", help="DONE.result 원본 JSON 도 출력")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    c = {k: "" for k in ("DIM", "BOLD", "CYAN", "GREEN", "YELLOW", "RED", "RESET")} if args.no_color \
        else {"DIM": DIM, "BOLD": BOLD, "CYAN": CYAN, "GREEN": GREEN,
              "YELLOW": YELLOW, "RED": RED, "RESET": RESET}

    posting = Path(args.posting).read_text(encoding="utf-8") if args.posting else SAMPLE_POSTING
    if args.no_evidence:
        evidences = []
    else:
        evidences = parse_evidences(Path(args.evidence)) if args.evidence else SAMPLE_EVIDENCES

    start = {
        "type": "START",
        "analysisId": str(uuid.uuid4()),
        "jobPosting": {"company": args.company, "role": args.role,
                       "career": args.career, "rawText": posting},
        "evidences": evidences,
    }

    print(f"{c['DIM']}브릿지 접속: {args.url}{c['RESET']}")
    print(f"{c['DIM']}공고 {len(posting)}자 · 자료 {len(evidences)}건{c['RESET']}\n")

    try:
        ws = connect(args.url, max_size=8 * 1024 * 1024, open_timeout=10)
    except Exception as exc:
        print(f"{c['RED']}브릿지에 접속하지 못했습니다: {exc}{c['RESET']}")
        print("먼저 브릿지를 띄우세요:  uv run uvicorn jobis_ai.webbridge.app:app --port 8100")
        return 1

    with ws:
        ws.send(json.dumps(start, ensure_ascii=False))
        while True:
            try:
                raw = ws.recv(timeout=900)
            except TimeoutError:
                print(f"{c['RED']}응답이 없습니다(15분). 브릿지 로그를 확인하세요.{c['RESET']}")
                return 1
            except Exception as exc:
                print(f"{c['RED']}연결이 끊겼습니다: {exc}{c['RESET']}")
                return 1

            m = json.loads(raw)
            kind = m.get("type")

            if kind == "PROGRESS":
                print(f"{c['DIM']}  {m['percent']:>3}% [{m['agent']}] {m['message']}{c['RESET']}")
            elif kind == "JOB_CONTEXT":
                print(f"{c['CYAN']}  공고 이해: {m['company']} / {m['role']} / {m['career']}{c['RESET']}")
                print(f"{c['CYAN']}  요구 기술: {', '.join(m['stack'])}{c['RESET']}")
            elif kind == "AGENT_MESSAGE":
                print(f"\n{c['GREEN']}[{m.get('agentName') or 'AI'}]{c['RESET']} {m['text']}\n")
            elif kind == "REQUEST_RESUME":
                print(f"\n{c['YELLOW']}[{m.get('agentName')}] 이력서 요청{c['RESET']}")
                print(f"  {m.get('text')}")
                if m.get("reason"):
                    print(f"  {c['DIM']}사유: {m['reason']}{c['RESET']}")
                print(f"  {c['DIM']}허용 형식: {', '.join(m.get('accept') or [])}{c['RESET']}")
                print(f"  {c['DIM']}파일 경로를 입력하거나, 그냥 Enter 로 건너뜁니다.{c['RESET']}")
                try:
                    given = input("  이력서 파일 경로> ").strip().strip('"')
                except (EOFError, KeyboardInterrupt):
                    given = ""
                resume = ""
                if given:
                    path = Path(given)
                    if path.exists():
                        # 텍스트 계열은 직접 읽고, pdf·docx 는 extract 에 맡긴다.
                        from jobis_ai.extract import extract_text
                        resume = (extract_text({"sourceType": "file", "value": str(path)}).text or "").strip()
                        print(f"  {c['DIM']}추출 {len(resume)}자{c['RESET']}")
                    else:
                        print(f"  {c['RED']}파일이 없습니다: {path}{c['RESET']}")
                ws.send(json.dumps({"type": "USER_MESSAGE", "analysisId": start["analysisId"],
                                    "text": resume, "replyTo": "resume"}, ensure_ascii=False))
            elif kind == "QUESTION":
                print(f"\n{c['YELLOW']}[{m.get('agentName')}] 질문 {m.get('index')}/{m.get('total')}{c['RESET']}")
                print(f"  {m['text']}")
                if m.get("reason"):
                    print(f"  {c['DIM']}왜 묻나: {m['reason']}{c['RESET']}")
                if m.get("options"):
                    print(f"  {c['DIM']}선택지: {' / '.join(m['options'])}{c['RESET']}")
                try:
                    answer = input("  답변> ").strip()
                except (EOFError, KeyboardInterrupt):
                    answer = ""
                ws.send(json.dumps({"type": "USER_MESSAGE", "analysisId": start["analysisId"],
                                    "text": answer, "replyTo": m.get("questionId")},
                                   ensure_ascii=False))
            elif kind == "DONE":
                print_report(m["result"], c)
                if args.json:
                    print("\n" + json.dumps(m["result"], ensure_ascii=False, indent=2))
                return 0
            elif kind == "ERROR":
                print(f"\n{c['RED']}오류 [{m.get('code')}] {m.get('message')}{c['RESET']}")
                print(f"  다음 행동: {', '.join(m.get('actions') or [])}")
                return 1
            else:
                print(f"{c['DIM']}  (알 수 없는 메시지: {kind}){c['RESET']}")


if __name__ == "__main__":
    sys.exit(main())
