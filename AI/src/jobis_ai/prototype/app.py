"""프로토타입 관찰 UI 서버 (개발 전용).

실행:
    PYTHONUTF8=1 uv run --with fastapi,uvicorn,python-multipart uvicorn jobis_ai.prototype.app:app --reload

브라우저에서 http://127.0.0.1:8000 접속 → 이력서·공고 원문과 메시지를 넣고 실행하면
플래너 선택 → 검증기 dispatch → 에이전트 → 그래프 노드 → LLM 입출력 → 요구사항별 판정
→ 점수 산출까지 전 과정이 타임라인으로 보인다. 모든 실행은 SQLite 에 저장된다.
세션은 기본으로 이어지며(대화 이력 유지), 이력서는 파일(.md/.txt/.docx/.pdf) 업로드도 된다.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from jobis_ai import trace
from jobis_ai.contracts.api import ChatAttachment, ChatRequest, SourceType
from jobis_ai.extract import extract_text
from jobis_ai.orchestrator.chat import handle_chat
from jobis_ai.prototype.db import RunStore
from jobis_ai.prototype.stepper import advance_step_run, get_step_run, start_step_run

app = FastAPI(title="jobis-ai 관찰 UI", docs_url=None, redoc_url=None)
_store = RunStore()


def _build_attachments(resume_text: str, posting_text: str) -> list[ChatAttachment]:
    attachments = []
    if resume_text.strip():
        attachments.append(ChatAttachment(
            kind="resume", sourceType=SourceType.text, value=resume_text,
        ))
    if posting_text.strip():
        attachments.append(ChatAttachment(
            kind="job_posting", sourceType=SourceType.text, value=posting_text,
        ))
    return attachments


class RunInput(BaseModel):
    message: str
    resumeText: str = ""
    postingText: str = ""
    # 이전 실행의 sessionId 를 주면 세션 자산(분석 결과 등)을 이어서 쓴다.
    sessionId: str = ""


@app.post("/api/run")
def run_turn(body: RunInput) -> dict:
    session_id = body.sessionId.strip() or str(uuid.uuid4())
    attachments = _build_attachments(body.resumeText, body.postingText)
    request = ChatRequest(sessionId=session_id, message=body.message, attachments=attachments)

    with trace.recording() as rec:
        response = handle_chat(request)

    run_id = _store.save_run(
        session_id=session_id,
        message=body.message,
        resume_text=body.resumeText or None,
        posting_text=body.postingText or None,
        response=response.model_dump(),
        trace_events=rec.events,
    )
    return {
        "runId": run_id,
        "sessionId": session_id,
        "response": response.model_dump(),
        "trace": rec.events,
    }


# --- 단계 실행 모드: 버튼 한 번에 한 분기씩 -------------------------------------
class StepStartInput(BaseModel):
    message: str
    resumeText: str = ""
    postingText: str = ""
    sessionId: str = ""


class StepNextInput(BaseModel):
    runId: str


class SayInput(BaseModel):
    sessionId: str
    message: str


@app.post("/api/step/start")
def step_start(body: StepStartInput) -> dict:
    """플래너+검증기까지만 실행하고 멈춘다. 이후는 /api/step/next 로 한 단계씩."""

    session_id = body.sessionId.strip() or str(uuid.uuid4())
    request = ChatRequest(
        sessionId=session_id, message=body.message,
        attachments=_build_attachments(body.resumeText, body.postingText),
    )
    snapshot = start_step_run(request)
    _maybe_save_step_run(snapshot["runId"], body)
    return snapshot


@app.post("/api/step/next")
def step_next(body: StepNextInput) -> dict:
    snapshot = advance_step_run(body.runId)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="step run not found")
    _maybe_save_step_run(body.runId, None)
    return snapshot


def _maybe_save_step_run(run_id: str, start_body: StepStartInput | None) -> None:
    """완료된 단계 실행을 1회만 DB 에 저장한다."""

    run = get_step_run(run_id)
    if run is None or not run.done or getattr(run, "_saved", False):
        return
    resume = posting = None
    for att in run._request.attachments:
        if att.kind == "resume":
            resume = att.value
        else:
            posting = att.value
    _store.save_run(
        session_id=run.session_id, message=run.message,
        resume_text=resume, posting_text=posting,
        response={
            "reply": " ".join(r for r in run.replies if r).strip(),
            "intent": run.intent_label, "confidence": run.confidence,
            "dispatched": list(run.results.keys()), "results": run.results,
            "followUpQuestions": run.follow_up, "warnings": run.warnings,
        },
        trace_events=run.events,
    )
    run._saved = True


@app.post("/api/step/say")
def step_say(body: SayInput) -> dict:
    """작업 중간의 자연어 발화 — 같은 세션으로 일반 턴을 즉시 처리한다."""

    with trace.recording() as rec:
        response = handle_chat(ChatRequest(sessionId=body.sessionId, message=body.message))
    _store.save_run(
        session_id=body.sessionId, message=body.message,
        resume_text=None, posting_text=None,
        response=response.model_dump(), trace_events=rec.events,
    )
    return {"reply": response.reply, "events": rec.events,
            "dispatched": response.dispatched, "intent": response.intent}


# --- 파일 업로드: 이력서/공고 파일 → 텍스트 추출 (extract.py 재사용) ----------------
_UPLOAD_SUFFIXES = {".md", ".txt", ".docx", ".pdf"}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)) -> dict:
    """업로드 파일에서 텍스트를 추출해 돌려준다. 프론트가 원문 입력칸에 채워 넣는다."""

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 형식: {suffix or '(확장자 없음)'} — md/txt/docx/pdf 만 가능해요.",
        )
    data = await file.read()
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        result = extract_text({"sourceType": "file", "value": str(tmp_path)})
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return {"filename": file.filename, "text": result.text, "warnings": result.warnings}


@app.get("/api/runs")
def list_runs() -> list[dict]:
    return _store.list_runs()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    record = _store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE


_PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>jobis-ai 관찰 UI</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg:#0f1420; --panel:#171e2e; --panel2:#1e2740; --border:#2a3550;
    --text:#dbe4f5; --dim:#8494b3; --accent:#5b8cff;
    --met:#2fbf71; --partial:#e0a52e; --notmet:#e05555; --uncertain:#8a7bd8;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.6 'Segoe UI', 'Malgun Gothic', sans-serif; }
  h1 { font-size:17px; margin:0; }
  header { padding:12px 20px; border-bottom:1px solid var(--border);
           display:flex; gap:12px; align-items:baseline; }
  header .sub { color:var(--dim); font-size:12px; }
  .layout { display:grid; grid-template-columns:380px 1fr; gap:0;
            height:calc(100vh - 49px); }
  .left { border-right:1px solid var(--border); overflow-y:auto; padding:16px; }
  .right { overflow-y:auto; padding:16px 24px; }
  label { display:block; font-size:12px; color:var(--dim); margin:12px 0 4px; }
  textarea, input[type=text] { width:100%; background:var(--panel); color:var(--text);
    border:1px solid var(--border); border-radius:6px; padding:8px; font:13px/1.5 Consolas, monospace; }
  input[type=file] { width:100%; color:var(--dim); font-size:12px; margin-bottom:4px; }
  input[type=file]::file-selector-button { background:var(--panel2); color:var(--text);
    border:1px solid var(--border); border-radius:6px; padding:4px 10px; cursor:pointer; margin-right:8px; }
  textarea { resize:vertical; }
  button { background:var(--accent); color:#fff; border:0; border-radius:6px;
           padding:9px 18px; font-size:14px; cursor:pointer; margin-top:14px; }
  button:disabled { opacity:.5; cursor:wait; }
  .runitem { padding:8px 10px; border:1px solid var(--border); border-radius:6px;
             margin-top:8px; cursor:pointer; font-size:12px; }
  .runitem:hover { background:var(--panel2); }
  .runitem .t { color:var(--dim); font-size:11px; }
  .reply { background:var(--panel2); border:1px solid var(--border); border-radius:8px;
           padding:14px 16px; margin-bottom:18px; white-space:pre-wrap; }
  .event { border:1px solid var(--border); border-left-width:4px; border-radius:8px;
           background:var(--panel); margin-bottom:10px; }
  .event > .head { display:flex; gap:10px; align-items:center; padding:9px 14px; }
  .event .kind { font-size:11px; font-weight:600; padding:2px 8px; border-radius:10px;
                 white-space:nowrap; }
  .event .label { flex:1; }
  .event .ms { color:var(--dim); font-size:11px; white-space:nowrap; }
  .event .body { padding:0 14px 12px; }
  .k-planner   { border-left-color:#5b8cff; } .k-planner .kind { background:#5b8cff33; color:#9ab8ff; }
  .k-fallback  { border-left-color:#e0a52e; } .k-fallback .kind { background:#e0a52e33; color:#eec36a; }
  .k-dispatch  { border-left-color:#38b6a5; } .k-dispatch .kind { background:#38b6a533; color:#7bd9cc; }
  .k-agent_start,.k-agent_end { border-left-color:#c268d8; }
  .k-agent_start .kind,.k-agent_end .kind { background:#c268d833; color:#dd9cec; }
  .k-node      { border-left-color:#7a869c; } .k-node .kind { background:#7a869c33; color:#aab6cc; }
  .k-llm_call  { border-left-color:#e0713a; } .k-llm_call .kind { background:#e0713a33; color:#f0a172; }
  .k-judgment  { border-left-color:#2fbf71; } .k-judgment .kind { background:#2fbf7133; color:#6fdca4; }
  .k-score     { border-left-color:#f2d24b; } .k-score .kind { background:#f2d24b33; color:#f5e08e; }
  .chip { display:inline-block; background:var(--panel2); border:1px solid var(--border);
          border-radius:12px; padding:1px 10px; margin:2px 3px 2px 0; font-size:12px; }
  .status { font-weight:600; padding:1px 8px; border-radius:10px; font-size:11px; }
  .s-met { background:#2fbf7126; color:var(--met); }
  .s-partially_met { background:#e0a52e26; color:var(--partial); }
  .s-not_met { background:#e0555526; color:var(--notmet); }
  .s-uncertain { background:#8a7bd826; color:var(--uncertain); }
  table { border-collapse:collapse; width:100%; font-size:12px; margin-top:6px; }
  th, td { border:1px solid var(--border); padding:5px 8px; text-align:left; vertical-align:top; }
  th { background:var(--panel2); color:var(--dim); font-weight:600; }
  details { margin-top:8px; }
  summary { cursor:pointer; color:var(--dim); font-size:12px; }
  pre { background:#0b0f18; border:1px solid var(--border); border-radius:6px;
        padding:10px; overflow-x:auto; font-size:12px; max-height:420px; overflow-y:auto;
        white-space:pre-wrap; word-break:break-word; }
  .dim { color:var(--dim); font-size:12px; }
  .grade { font-size:15px; font-weight:700; }
  .empty { color:var(--dim); padding:40px; text-align:center; }
  .sessionrow { display:flex; gap:8px; align-items:center; margin-top:10px; font-size:12px; color:var(--dim); }
  .chatlog { max-height:300px; overflow-y:auto; }
  .turndiv { margin:20px 0 12px; color:var(--accent); font-size:12px; font-weight:600;
             border-top:1px dashed var(--border); padding-top:10px; }
  .chatlog .m { margin-top:8px; padding:8px 10px; border-radius:8px; font-size:12px; white-space:pre-wrap; }
  .chatlog .me { background:#25335a; }
  .chatlog .bot { background:var(--panel2); border:1px solid var(--border); }
</style>
</head>
<body>
<header>
  <h1>jobis-ai 관찰 UI</h1>
  <span class="sub">플래너 → 검증기 → 에이전트 → 판정 엔진 — 모든 단계를 기록·표시 (개발 전용)</span>
</header>
<div class="layout">
  <div class="left">
    <label>메시지 (자연어 요청)</label>
    <input type="text" id="message" value="이 공고 나 되나?">
    <label>이력서 원문 (텍스트 붙여넣기 또는 파일 업로드: .md / .txt / .docx / .pdf)</label>
    <input type="file" id="resumeFile" accept=".md,.txt,.docx,.pdf" onchange="uploadResume(this)">
    <div id="resumeFileInfo" class="dim"></div>
    <textarea id="resume" rows="9" placeholder="이력서 텍스트를 붙여넣거나 위에서 파일을 올리세요"></textarea>
    <label>공고 원문 (비정형 텍스트)</label>
    <textarea id="posting" rows="9" placeholder="채용 공고 텍스트를 붙여넣으세요"></textarea>
    <div class="sessionrow">
      <span id="sessionLabel">세션: 첫 실행 때 생성 (이후 대화 맥락 자동 유지)</span>
      <button onclick="newSession()" style="margin-top:0; padding:3px 10px; font-size:12px; background:#2a3550;">새 세션</button>
    </div>
    <div style="display:flex; gap:8px;">
      <button id="runBtn" onclick="run()">전체 실행 →</button>
      <button id="stepStartBtn" onclick="stepStart()" style="background:#38b6a5;">단계 실행 ⏯</button>
    </div>
    <div id="stepBar" style="display:none; margin-top:12px; padding:10px 12px; border:1px solid var(--accent); border-radius:8px;">
      <div class="dim" id="stepNextLabel" style="margin-bottom:6px;"></div>
      <button id="stepNextBtn" onclick="stepNext()" style="margin-top:0;">다음 단계 ▶</button>
    </div>
    <label>자연어 메시지 — 작업 중간에도 보낼 수 있어요 (같은 세션으로 즉시 처리)</label>
    <div style="display:flex; gap:6px;">
      <input type="text" id="sayMsg" placeholder="예: 자소서도 써줘" style="flex:1" onkeydown="if(event.key==='Enter')say()">
      <button id="sayBtn" onclick="say()" style="margin-top:0;">보내기</button>
    </div>
    <div id="chatLog" class="chatlog"></div>
    <h1 style="margin-top:24px; font-size:14px;">지난 실행 (DB)</h1>
    <div id="runs"></div>
  </div>
  <div class="right" id="out"><div class="empty">왼쪽에서 이력서·공고·메시지를 넣고 실행하세요.</div></div>
</div>
<script>
let lastSessionId = "";

function updateSessionLabel(){
  document.getElementById("sessionLabel").textContent = lastSessionId
    ? `세션 유지 중: ${lastSessionId.slice(0,8)}… (대화 맥락 이어짐)`
    : "세션: 첫 실행 때 생성 (이후 대화 맥락 자동 유지)";
}
function newSession(){
  lastSessionId = "";
  document.getElementById("chatLog").innerHTML = "";
  resetTimeline();
  document.getElementById("out").innerHTML = '<div class="empty">새 세션 — 이력서·공고·메시지를 넣고 실행하세요.</div>';
  updateSessionLabel();
}
function appendChat(cls, text){
  if (!text) return;
  const log = document.getElementById("chatLog");
  log.innerHTML += `<div class="m ${cls}">${cls==="me"?"나: ":""}${esc(text)}</div>`;
  log.scrollTop = log.scrollHeight;
}

async function uploadResume(input){
  const f = input.files[0];
  if (!f) return;
  const info = document.getElementById("resumeFileInfo");
  info.textContent = `추출 중… ${f.name}`;
  const fd = new FormData();
  fd.append("file", f);
  try{
    const res = await fetch("/api/upload", {method:"POST", body: fd});
    const d = await res.json();
    if (!res.ok){ info.textContent = `실패: ${d.detail || res.status}`; return; }
    document.getElementById("resume").value = d.text;
    info.textContent = `${d.filename} → ${d.text.length}자 추출`
      + ((d.warnings||[]).length ? ` · 경고: ${d.warnings.map(w=>w.message).join(" / ")}` : "");
  } catch(e){
    info.textContent = `업로드 실패: ${e}`;
  }
  input.value = "";
}

const KIND_KO = {
  planner:"플래너", fallback:"폴백", dispatch:"dispatch", agent_start:"에이전트 시작",
  agent_end:"에이전트 종료", node:"그래프 노드", llm_call:"LLM 호출",
  judgment:"매칭 판정", score:"점수 산출",
};
const NODE_KO = {
  parse_job_posting:"공고 파싱(LLM 읽기)", build_user_profile:"프로필 구축(LLM 읽기)",
  check_profile_completeness:"프로필 완결성(룰)", check_sufficiency:"충분성 게이트(룰)",
  ask_user:"되묻기 생성", analyze_gap:"갭 판정(결정론)", plan_roadmap:"로드맵 계획(룰)",
  find_alternatives:"대안 탐색(룰)", verify_result:"검증(룰 4종)", assemble_output:"응답 조립+nl_render",
};

function esc(s){ return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function pre(obj){ return `<pre>${esc(typeof obj==="string"?obj:JSON.stringify(obj,null,2))}</pre>`; }
function raw(detail){ return `<details><summary>원본 JSON</summary>${pre(detail)}</details>`; }
function chips(arr){ return (arr||[]).map(a=>`<span class="chip">${esc(a)}</span>`).join("") || '<span class="dim">없음</span>'; }
function statusBadge(s){ return `<span class="status s-${esc(s)}">${esc(s)}</span>`; }

const RENDER = {
  planner(d){
    return `선택: ${chips(d.selectedAgents)} <span class="dim">confidence=${d.confidence}</span><br>
            <span class="dim">세션 자산: </span>${chips(d.sessionAssets)}
            ${d.target?`<br><span class="dim">대상 참조: ${esc(d.target)}</span>`:""}`;
  },
  fallback(d){ return `의도 라벨: <span class="chip">${esc(d.intent)}</span> <span class="dim">confidence=${d.confidence}</span>`; },
  dispatch(d){
    if(d.ask) return `실행 없이 되묻기: <b>${esc(d.ask)}</b>`;
    return `최종 실행 시퀀스: ${chips(d.agents)}<br><span class="dim">${esc(d.note)}</span>`;
  },
  agent_start(d){
    return `<b>${esc(d.agent)}</b> — ${esc(d.description)}<br>
            <span class="dim">전제조건: </span>${chips(d.preconditions)}
            <span class="dim"> / 보유 자산: </span>${chips(d.sessionAssets)}`;
  },
  agent_end(d){
    return `${d.reply?`응답: <b>${esc(d.reply)}</b><br>`:""}
            <span class="dim">세션에 저장: </span>${chips(d.sessionUpdates)}
            ${(d.followUpQuestions||[]).length?`<br><span class="dim">추가 질문 ${d.followUpQuestions.length}건</span>`:""}
            <details><summary>산출물(data) 펼치기</summary>${pre(d.data)}</details>
            ${(d.warnings||[]).length?`<details><summary>경고 ${d.warnings.length}건</summary>${pre(d.warnings)}</details>`:""}`;
  },
  node(d){
    const keys = Object.keys(d.update||{});
    return `<span class="chip">${esc(NODE_KO[d.node]||d.node)}</span>
            ${d.status?`<span class="dim">status=${esc(d.status)}</span>`:""}
            <br><span class="dim">갱신한 상태 키: </span>${chips(keys)}
            <details><summary>노드가 갱신한 상태 전체</summary>${pre(d.update)}</details>`;
  },
  llm_call(d){
    const ok = d.outcome==="ok";
    return `<b>${esc(d.node)}</b> → 스키마 <span class="chip">${esc(d.schema)}</span>
            <span class="status ${ok?"s-met":(d.outcome==="not_configured"?"s-uncertain":"s-not_met")}">${esc(d.outcome)}</span>
            ${d.attempt>1?`<span class="dim">(${d.attempt}번째 시도 성공)</span>`:""}
            ${d.error?`<br><span class="dim">오류: ${esc(d.error)}</span>`:""}
            ${d.systemPrompt?`<details><summary>시스템 프롬프트</summary>${pre(d.systemPrompt)}</details>`:""}
            ${d.input?`<details><summary>입력 원문 (${d.input.length}자)</summary>${pre(d.input)}</details>`:""}
            ${d.output?`<details open><summary>구조화 출력 (파싱 결과)</summary>${pre(d.output)}</details>`:""}`;
  },
  judgment(d){
    const rows = (d.matches||[]).map(m=>`<tr>
      <td>${esc(m.text)}<br><span class="dim">${esc(m.requirementId)} · ${esc(m.type)}</span></td>
      <td>${esc(m.kind)}</td><td>${esc(m.method)}</td>
      <td>${statusBadge(m.status)}<br><span class="dim">conf=${m.confidence}</span></td>
      <td>${chips(m.matchedSkills)}${(m.missingSkills||[]).length?`<br><span class="dim">결측:</span> ${chips(m.missingSkills)}`:""}</td>
      <td>${chips(m.matchedEvidenceIds)}</td>
      <td class="dim">${esc(m.reason)}</td></tr>`).join("");
    return `<table><tr><th>요구사항</th><th>종류</th><th>판정 방법</th><th>판정</th>
            <th>매칭/결측 스킬</th><th>근거 ID</th><th>판정 사유</th></tr>${rows}</table>
            ${d.llmUnavailable?`<div class="dim">LLM 불가로 판정 못 한 건: ${d.llmUnavailable} (uncertain 유지)</div>`:""}`;
  },
  score(d){
    const used = d.usedCategories||{};
    const rows = Object.entries(d.categoryScores||{}).map(([k,v])=>{
      const u = used[k];
      return `<tr><td>${esc(k)}</td><td>${v===null?'<span class="dim">None (계산 근거 없음 → 분모 제외)</span>':v}</td>
              <td>${u?u.weight:'<span class="dim">—</span>'}</td></tr>`;
    }).join("");
    return `<table><tr><th>카테고리</th><th>점수</th><th>가중치</th></tr>${rows}</table>
            <div style="margin-top:8px">가중 평균 <b>${d.weightedScore ?? "—"}</b>
            ${d.thresholds?`<span class="dim"> (상 ≥ ${d.thresholds["상"]}, 중 ≥ ${d.thresholds["중"]})</span>`:""}
            → <span class="grade">등급 ${esc(d.grade)}</span></div>`;
  },
};

function renderEvent(ev){
  if (ev.__turn !== undefined){
    return `<div class="turndiv">── 턴 ${ev.__n}: “${esc(ev.__turn)}” ──</div>`;
  }
  const body = (RENDER[ev.kind]||(()=>""))(ev.detail||{});
  return `<div class="event k-${ev.kind}">
    <div class="head">
      <span class="kind">${esc(KIND_KO[ev.kind]||ev.kind)}</span>
      <span class="label">${esc(ev.label)}</span>
      <span class="ms">#${ev.seq} · +${ev.elapsedMs}ms${ev.detail&&ev.detail.durationMs?` · ${ev.detail.durationMs}ms 소요`:""}</span>
    </div>
    <div class="body">${body}${raw(ev.detail)}</div>
  </div>`;
}

// 현재 화면 상태 — 세션이 이어지는 동안 턴 구분선과 함께 누적한다 (초기화는 [새 세션]).
let current = { reply: "", meta: "", events: [], raw: null };
let stepRun = null;   // {runId, done}
let turnCount = 0;

function resetTimeline(){
  current = { reply: "", meta: "", events: [], raw: null };
  turnCount = 0;
}
function startTurnEvents(msg){
  turnCount += 1;
  current.events.push({__turn: msg || "(첨부만 전송)", __n: turnCount});
}

function renderCurrent(){
  document.getElementById("out").innerHTML = `
    <div class="reply"><b>${stepRun && !stepRun.done ? "진행 중 응답 (단계 실행)" : "최종 응답"}</b><br>${esc(current.reply)}
      <div class="dim" style="margin-top:6px">${current.meta}</div>
      ${current.raw ? `<details><summary>응답 전체 JSON</summary>${pre(current.raw)}</details>` : ""}
    </div>
    <h1 style="font-size:14px; margin-bottom:10px;">실행 타임라인 — 턴 ${turnCount||1}개 · 이벤트 ${current.events.filter(e=>e.__turn===undefined).length}건 (세션 누적)</h1>
    ${current.events.map(renderEvent).join("")}`;
  document.getElementById("out").scrollTop = document.getElementById("out").scrollHeight;
}

function renderRun(data){
  // 지난 실행(DB) 열람용 — 저장된 1회 실행만 보여준다 (누적 타임라인과 별개).
  const r = data.response;
  stepRun = null;
  document.getElementById("stepBar").style.display = "none";
  resetTimeline();
  current = {
    reply: r.reply,
    meta: `intent=${esc(r.intent)} · confidence=${r.confidence} · dispatched=[${(r.dispatched||[]).join(", ")}] · session=${esc(data.sessionId||data.session_id)}`,
    events: data.trace, raw: r,
  };
  renderCurrent();
}

function accumulateTurn(userMsg, events, reply, meta, raw){
  // 세션 이어서 대화 — 타임라인을 초기화하지 않고 턴 구분선과 함께 누적한다.
  stepRun = null;
  document.getElementById("stepBar").style.display = "none";
  startTurnEvents(userMsg);
  current.events = current.events.concat(events || []);
  current.reply = reply;
  current.meta = meta;
  current.raw = raw;
  renderCurrent();
}

function _formBody(){
  return {
    message: document.getElementById("message").value,
    resumeText: document.getElementById("resume").value,
    postingText: document.getElementById("posting").value,
    sessionId: lastSessionId,   // 기본이 세션 유지 — 새로 시작하려면 [새 세션] 버튼
  };
}

async function run(){
  const btn = document.getElementById("runBtn");
  const body = _formBody();
  btn.disabled = true; btn.textContent = "실행 중… (첫 분석은 수십 초)";
  try{
    const res = await fetch("/api/run", {method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
    const data = await res.json();
    lastSessionId = data.sessionId;
    updateSessionLabel();
    appendChat("me", body.message);
    appendChat("bot", data.response.reply);
    accumulateTurn(body.message, data.trace, data.response.reply,
      `intent=${esc(data.response.intent)} · confidence=${data.response.confidence} · dispatched=[${(data.response.dispatched||[]).join(", ")}] · session=${esc(data.sessionId)}`,
      data.response);
    loadRuns();
  } catch(e){
    document.getElementById("out").innerHTML = `<div class="empty">실행 실패: ${esc(e)}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "전체 실행 →";
  }
}

// --- 단계 실행: 버튼 한 번에 한 분기 -----------------------------------------
function _updateStepBar(d){
  const bar = document.getElementById("stepBar");
  if (d.done){
    bar.style.display = "none";
    stepRun = null;
    appendChat("me", stepUserMsg);
    appendChat("bot", d.reply);
    stepUserMsg = "";
    loadRuns();
  } else {
    bar.style.display = "block";
    document.getElementById("stepNextLabel").textContent = "다음: " + d.nextLabel;
  }
}

let stepUserMsg = "";

async function stepStart(){
  const btn = document.getElementById("stepStartBtn");
  const body = _formBody();
  stepUserMsg = body.message;
  btn.disabled = true; btn.textContent = "계획 수립 중…";
  try{
    const res = await fetch("/api/step/start", {method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
    const d = await res.json();
    lastSessionId = d.sessionId;
    updateSessionLabel();
    stepRun = { runId: d.runId, done: d.done };
    startTurnEvents(body.message);
    current.events = current.events.concat(d.events);
    current.reply = d.reply;
    current.raw = null;
    current.meta = `단계 실행 · intent=${esc(d.intent)} · confidence=${d.confidence} · 남은 단계=[${(d.dispatchedPending||[]).join(", ")}] · session=${esc(d.sessionId)}`;
    _updateStepBar(d);
    renderCurrent();
  } finally {
    btn.disabled = false; btn.textContent = "단계 실행 ⏯";
  }
}

async function stepNext(){
  if (!stepRun) return;
  const btn = document.getElementById("stepNextBtn");
  btn.disabled = true; btn.textContent = "실행 중…";
  try{
    const res = await fetch("/api/step/next", {method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({runId: stepRun.runId})});
    const d = await res.json();
    stepRun.done = d.done;
    current.reply = d.reply;
    current.events = current.events.concat(d.events);
    current.meta = `단계 실행 · 방금: ${esc(d.label)} · 남은 단계=[${(d.dispatchedPending||[]).join(", ")}] · session=${esc(d.sessionId)}`;
    _updateStepBar(d);
    renderCurrent();
  } finally {
    btn.disabled = false; btn.textContent = "다음 단계 ▶";
  }
}

// --- 자연어 발화: 작업 중간에도 같은 세션으로 즉시 처리 -------------------------
async function say(){
  const input = document.getElementById("sayMsg");
  const text = input.value.trim();
  if (!text) return;
  if (!lastSessionId){ lastSessionId = crypto.randomUUID(); updateSessionLabel(); }
  const btn = document.getElementById("sayBtn");
  btn.disabled = true;
  appendChat("me", text);
  try{
    const res = await fetch("/api/step/say", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({sessionId: lastSessionId, message: text})});
    const d = await res.json();
    appendChat("bot", d.reply);
    startTurnEvents(text);                              // 발화 처리 과정도 턴 구분선과 함께 누적
    current.events = current.events.concat(d.events);
    renderCurrent();
    input.value = "";
    loadRuns();
  } finally {
    btn.disabled = false;
  }
}

async function loadRuns(){
  const runs = await (await fetch("/api/runs")).json();
  document.getElementById("runs").innerHTML = runs.map(r=>
    `<div class="runitem" onclick="openRun('${r.id}')">
       <div>${esc(r.message)}</div>
       <div class="t">${esc(r.created_at.replace("T"," ").slice(0,19))} · ${r.id.slice(0,8)}</div>
     </div>`).join("") || '<div class="dim">저장된 실행 없음</div>';
}

async function openRun(id){
  const data = await (await fetch("/api/runs/"+id)).json();
  lastSessionId = data.session_id;
  updateSessionLabel();
  renderRun(data);
}

loadRuns();
</script>
</body>
</html>
"""
