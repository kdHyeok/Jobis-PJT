/* ============================================================
   잡이스 — 가짜 AI 에이전트 서버 (진짜 AI가 살 자리의 "옆집")
   한 프로그램에서 두 가지를 흉내낸다:
     · WebSocket(:8000)  — 실시간 분석 대화 (공고이해 JOB_CONTEXT → 진행 → 질문(하나씩) → 로드맵 DONE)
     · HTTP POST /extract — 커리어 저장소 자료 파편화 (원샷)

   웹백엔드는 "원문만 전달", 분석/파싱은 전부 여기서 한다.
   시연용(하서진 이력서 × ㈜쉴드원 공고)은 큐레이팅된 신호를 내고,
   그 외 입력은 일반 휴리스틱으로 처리한다. 진짜 AI가 붙으면 이 서버만 교체.
   ============================================================ */
'use strict';
const http = require('http');
const { WebSocketServer } = require('ws');
const fs = require('fs');
const path = require('path');

const PORT = 8000;
const STAGE_MS = 10000;   // 진행 신호 간격(ms)
const RESULT = JSON.parse(fs.readFileSync(path.join(__dirname, 'result.json'), 'utf8')); // 일반 결과(폴백)

const sessions = new Map();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ── HTTP(저장소 파싱) + WebSocket(분석)을 같은 포트/프로그램에서 ── */
const httpServer = http.createServer((req, res) => {
  if (req.method === 'POST' && req.url === '/extract') {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      let payload = {};
      try { payload = JSON.parse(body || '{}'); } catch (e) {}
      const fragments = extractEvidence(payload.sourceType || 'TEXT', payload.content || '');
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ fragments }));
      console.log(`  [HTTP] /extract → 조각 ${fragments.length}개`);
    });
    return;
  }
  if (req.method === 'POST' && req.url === '/roadmap') {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      let payload = {};
      try { payload = JSON.parse(body || '{}'); } catch (e) {}
      const roadmap = generateRoadmap(payload);
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(roadmap));
      console.log(`  [HTTP] /roadmap → ${payload.company} / ${payload.routeKind}${payload.goalCompany ? ' → ' + payload.goalCompany : ''}`);
    });
    return;
  }
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('not found');
});

const wss = new WebSocketServer({ server: httpServer });
httpServer.listen(PORT, () => {
  console.log(`🤖 가짜 AI 서버 대기 중 …  ws://localhost:${PORT}  (+ POST http://localhost:${PORT}/extract)`);
  console.log('   웹백엔드/브라우저가 접속해서 START를 보내면 분석을 시작합니다.\n');
});

wss.on('connection', (ws) => {
  console.log('🔌 접속됨');
  ws.on('message', (raw) => {
    let msg;
    try { msg = JSON.parse(raw.toString()); } catch (e) { return; }
    handle(ws, msg);
  });
  ws.on('close', () => console.log('❌ 접속 종료'));
});

function send(ws, obj) {
  ws.send(JSON.stringify(obj));
  console.log('  → 보냄:', obj.type, obj.stage || obj.text || (obj.result ? '(결과)' : ''));
}

function handle(ws, msg) {
  console.log('  ← 받음:', msg.type, msg.text || '');
  if (msg.type === 'START') {
    runAnalysis(ws, msg);
  } else if (msg.type === 'USER_MESSAGE') {
    const s = sessions.get(msg.analysisId);
    if (s && s.resolveAnswer) {
      s.resolveAnswer(msg.text);
      s.resolveAnswer = null;
    }
  }
}

async function runAnalysis(ws, start) {
  const id = start.analysisId;
  const session = { ws, resolveAnswer: null };
  sessions.set(id, session);
  const rawJob = (start.jobPosting && start.jobPosting.rawText) || '';
  const sc = pickScenario(rawJob);
  console.log(`\n▶ 분석 시작  analysisId=${id}  (시나리오=${sc.name})`);

  // 0) 공고 이해 → JOB_CONTEXT (웹은 원문만 넘겼고, 구조화는 여기서)
  await sleep(1500);
  const ctx = sc.ctx;
  console.log(`  · 공고 파악: ${ctx.company} / ${ctx.role} / 요구스택 ${ctx.stack.length}개`);
  send(ws, { type: 'JOB_CONTEXT', analysisId: id, company: ctx.company, role: ctx.role, career: ctx.career, stack: ctx.stack });

  // 1차 진행
  for (const [stage, pct] of [['공고 요구사항 분석', 30], ['내 자료 대조', 50]]) {
    await sleep(STAGE_MS);
    send(ws, { type: 'PROGRESS', analysisId: id, stage, percent: pct });
  }

  // 질문 — 하나씩 (답하면 다음 질문)
  const questions = sc.questions;
  for (const q of questions) {
    await sleep(700);
    send(ws, { type: 'QUESTION', analysisId: id, questionId: q.questionId, field: q.field, text: q.text, options: q.options, isBlocking: true });
    const answer = await waitForAnswer(session);
    console.log('  ✎ 답변:', answer);
    await sleep(500);
    send(ws, { type: 'AGENT_MESSAGE', analysisId: id, text: q.followup || `"${answer}" 확인했어요. 반영할게요.`, interrupted: false });
  }

  // 2차 진행 (답변 반영)
  for (const [stage, pct] of [['답변 반영', 75], ['준비 로드맵 생성', 95]]) {
    await sleep(STAGE_MS);
    send(ws, { type: 'PROGRESS', analysisId: id, stage, percent: pct });
  }

  // 완료 → 결과
  await sleep(600);
  send(ws, { type: 'DONE', analysisId: id, result: sc.result });
  console.log('✔ 완료\n');
  sessions.delete(id);
}

function waitForAnswer(session) {
  return new Promise((resolve) => { session.resolveAnswer = resolve; });
}

/* ============================================================
   시연 큐레이팅 — 하서진 이력서 × ㈜쉴드원 보안 솔루션 엔지니어(EDR)
   이 두 입력이 들어오면 실제처럼 앞뒤 맞는 신호를 낸다.
   ============================================================ */
function isShieldPosting(raw) {
  const s = String(raw || '');
  return /49480707/.test(s) || (/쉴드원/.test(s) && /보안/.test(s));
}

const SHIELD_CONTEXT = {
  company: '㈜쉴드원',
  role: '보안 솔루션 엔지니어(EDR)',
  career: '경력 1년↑(신입 불가)',
  stack: ['EDR', 'SentinelOne', '악성코드·랜섬웨어 대응', 'Windows', 'Linux', 'macOS', '보안 전반', '정보보안기사(우대)'],
};

const SHIELD_QUESTIONS = [
  {
    questionId: 'q1', field: 'edr_exp',
    text: 'EDR·엔드포인트 보안 솔루션(SentinelOne·XDR·백신)을 직접 다뤄본 경험이 있나요?',
    options: ['실무 경험 있음', '교육·학습만', '없음'],
    followup: '엔드포인트 보안 솔루션 실무 경험을 준비도와 로드맵에 반영할게요.',
  },
  {
    questionId: 'q2', field: 'attack_depth',
    text: '0xARMOURY(MITRE ATT&CK) 프로젝트에서 어디까지 해보셨나요?',
    options: ['탐지·분석까지 구현', '공격 시뮬레이션 위주', '문서·이론 위주'],
    followup: '공격 관점 이해를 “탐지 관점”으로 잇는 걸 로드맵에 넣을게요. 좋은 차별점이에요.',
  },
  {
    questionId: 'q3', field: 'cert',
    text: '정보보안기사 등 보안 자격증은 어떤 상태인가요?',
    options: ['보유', '준비 중', '없음'],
    followup: '자격증 상태를 준비도에 반영했어요.',
  },
];

const SHIELD_RESULT = {
  readiness: { now: 52, goal: 76, topGap: 'EDR 실무 운영', judge: '보안 배경은 탄탄 · 엔드포인트 실무로 연결하면 경쟁력↑' },
  roadmap: [
    { no: 1, title: 'EDR 실무 감각', meta: '오픈소스 EDR로 엔드포인트 로그·탐지룰 실습', delta: '+10', status: 'active' },
    { no: 2, title: '악성코드·침해대응 실습', meta: '샌드박스 행위 분석 → ATT&CK 매핑 리포트', delta: '+8', status: 'locked' },
    { no: 3, title: '정보보안기사 필기', meta: '전공 배경 활용', delta: '+6', status: 'locked' },
  ],
  gaps: [
    { requirement: 'EDR·엔드포인트 솔루션 실무', mark: 'tri', fix: 'Wazuh 등 오픈소스 EDR 실습' },
    { requirement: '악성코드·침해대응 실무', mark: 'tri', fix: '샌드박스 행위 분석' },
    { requirement: 'Windows·Linux·macOS 기초', mark: 'ok', evidence: '정보보호 전공·학습' },
    { requirement: '보안 전반 지식', mark: 'ok', evidence: '세종대 정보보호학과' },
    { requirement: '정보보안기사', mark: 'tri', fix: '필기 준비 중' },
    { requirement: '경력 1년↑', mark: 'no', fix: '실무형 프로젝트·인턴으로 보완' },
  ],
  artifact: { title: '0xARMOURY 탐지 확장' },
  // 준비·지원 경로 2~3개 (스펙 §11). 웹은 카드로 보여주고 사용자가 "주 경로"를 선택한다.
  // kind: as_is(지금 지원) / reinforce(보강 후 지원) / parallel(유사공고 병행 → relatedPostings로 대체공고와 연결).
  // 종합 점수는 카드에 넣지 않는다(스펙 §10.5) — 준비 부담(effort)과 증거만.
  routes: [
    {
      id: 'as_is', kind: 'as_is', title: '지금 증거로 바로 지원',
      summary: '0xARMOURY·KISIA 활동을 EDR 관점으로 재정리해 쉴드원에 곧바로 지원하는 경로예요.',
      confirmed: ['정보보호 전공·보안 지식', '0xARMOURY(ATT&CK) 프로젝트'],
      missing: ['EDR·엔드포인트 실무 증거'],
      hardRisk: true, effort: 'low', deliverable: null,
      benefits: ['가장 빠름', '이미 가진 강점을 그대로 활용'],
      risks: ['경력 1년↑ 필수조건과 충돌 · EDR 실무 증거가 얇음'],
      relatedPostings: [],
      applyGuide: {
        matches: [
          { requirement: '보안 전반·정보보호 지식', evidence: '세종대 정보보호학과 · KISIA AI보안 교육', angle: '전공·교육 이력으로 기본기를 보여주기' },
          { requirement: '공격 관점 이해(ATT&CK)', evidence: '0xARMOURY(MITRE ATT&CK) 졸업프로젝트', angle: '"공격을 아는 만큼 탐지에 활용 가능"으로 연결' },
          { requirement: 'EDR·엔드포인트 실무', evidence: '(선택 자료에서 미확인)', angle: '실무 대신 학습·프로젝트 경험을 솔직하게 서술' },
        ],
        checklist: [
          '0xARMOURY를 "탐지 관점"으로 다시 서술했는가',
          '경력 1년↑ 조건을 어떻게 다룰지 정했는가(솔직하게)',
          '지원서에 결과물 링크가 연결돼 있는가',
        ],
      },
    },
    {
      id: 'reinforce', kind: 'reinforce', title: '산출물 하나 만들고 지원',
      summary: 'ELK로 EDR 로그 탐지룰을 만들어 가장 큰 격차(EDR 실무)를 직접 메운 뒤 지원하는 경로예요.',
      confirmed: ['정보보호 전공·보안 지식', '0xARMOURY(ATT&CK) 프로젝트'],
      missing: ['EDR·엔드포인트 실무 증거'],
      hardRisk: true, effort: 'mid', deliverable: 'ELK로 EDR 로그 탐지룰 만들기',
      benefits: ['가장 큰 격차를 정확히 겨냥', '지원 시 증거로 바로 활용'],
      risks: ['2~3주 준비 기간 필요 · 경력 필수조건은 여전히 남음'],
      relatedPostings: [],
    },
    {
      id: 'parallel', kind: 'parallel', title: '유사 공고 병행하며 실무 축적',
      summary: '지금 지원 가능한 대안·디딤돌 공고를 함께 보며 EDR 실무 경력 자체를 쌓아 쉴드원으로 잇는 경로예요.',
      confirmed: ['정보보호 전공·보안 지식'],
      missing: ['EDR·엔드포인트 실무 경력'],
      hardRisk: false, effort: 'high', deliverable: null,
      benefits: ['실무 경력 자체를 축적', '지금 지원 가능한 공고 포함'],
      risks: ['목표(쉴드원)까지 시간이 가장 김'],
      relatedPostings: ['dsntech', 'hyundai'],
    },
  ],
  // 대체 공고: 경로 parallel(유사공고 병행)을 고르면 이 목록을 보여주고, 고르면 rawText로 재분석(독립 세션).
  alternatives: [
    {
      id: 'dsntech', company: '㈜디에스앤텍', role: '보안솔루션 구축·유지보수 엔지니어', career: '신입~6년',
      label: '디딤돌', reason: '쉴드원 EDR 실무를 여기서 직접 쌓는 디딤돌 (보안솔루션 구축·로그 분석)',
      rawText: 'https://www.jobkorea.co.kr/Recruit/GI_Read/49585116?Oem_Code=C1&logpath=1&stext=EDR&listno=13&sc=630',
    },
    {
      id: 'hyundai', company: '㈜현대퓨처넷', role: '정보보안 (신입)', career: '신입',
      label: '대안', reason: '지금 바로 지원 가능 · 정보보안 전공/교육 우대와 딱 매칭',
      rawText: 'https://www.jobkorea.co.kr/Recruit/GI_Read/49341103?Oem_Code=C1&logpath=1&stext=%EB%B3%B4%EC%95%88&listno=21&sc=630',
    },
  ],
};

/* ── 대체 공고 시나리오: 디에스앤텍(디딤돌) / 현대퓨처넷(대안) ── */
function isDsntech(raw) { return /49585116/.test(String(raw)) || /디에스앤텍/.test(String(raw)); }
function isHyundai(raw) { return /49341103/.test(String(raw)) || /현대퓨처넷/.test(String(raw)); }

const DSNTECH_CONTEXT = {
  company: '㈜디에스앤텍', role: '보안솔루션 구축·유지보수 엔지니어', career: '신입~6년',
  stack: ['EDR', 'SIEM', 'UTM', 'Linux', 'Shell', 'Python', '로그 분석', '네트워크·가상화'],
};
const DSNTECH_QUESTIONS = [
  { questionId: 'd1', field: 'linux_exp', text: 'Linux 서버 운영·Shell 스크립트 경험은 어느 정도인가요?',
    options: ['실무 경험', '학습·과제 수준', '거의 없음'], followup: 'Linux·로그 분석 실무 감각을 로드맵에 반영할게요.' },
  { questionId: 'd2', field: 'log_analysis', text: '방화벽·EDR 같은 보안장비 로그를 분석해본 경험이 있나요?',
    options: ['분석 경험 있음', 'ATT&CK 등 이론만', '없음'], followup: 'ATT&CK 이해를 로그 분석·탐지로 잇는 걸 넣을게요.' },
  { questionId: 'd3', field: 'field_work', text: '고객사 설치·기술지원 외근직 업무도 괜찮으신가요?',
    options: ['좋아요', '상관없음', '내근 선호'], followup: '근무 형태 선호를 참고했어요.' },
];
const DSNTECH_RESULT = {
  readiness: { now: 64, goal: 82, topGap: 'Linux·로그분석 실무', judge: '보안솔루션·EDR 실무를 여기서 쌓기 좋음 · Python·전공·ATT&CK가 로그분석으로 연결' },
  roadmap: [
    { no: 1, title: 'Linux+Shell 로그분석 실습', meta: 'ELK 스택으로 로그 수집·분석', delta: '+8', status: 'active' },
    { no: 2, title: '오픈소스 보안솔루션 운영', meta: 'Wazuh 설치·엔드포인트 로그 탐지룰', delta: '+6', status: 'locked' },
    { no: 3, title: 'ATT&CK 로그 매핑 미니프로젝트', meta: '공격 시뮬레이션 → 탐지 리포트', delta: '+4', status: 'locked' },
  ],
  gaps: [
    { requirement: 'Linux 운영·Shell', mark: 'tri', fix: 'ELK 로그분석 실습' },
    { requirement: '보안솔루션(EDR/SIEM) 설치·운영', mark: 'tri', fix: 'Wazuh 실습' },
    { requirement: '로그 분석 실무', mark: 'tri', fix: 'ATT&CK 로그 매핑' },
    { requirement: 'Python 스크립트', mark: 'ok', evidence: '보유' },
    { requirement: '정보보호 전공·보안 지식', mark: 'ok', evidence: '세종대 정보보호학과' },
    { requirement: '네트워크·가상화 기초', mark: 'tri', fix: 'TCP/IP·VMware 기초' },
  ],
  artifact: { title: 'ELK로 EDR 로그 탐지룰 만들기' },
  routes: [
    {
      id: 'as_is', kind: 'as_is', title: '지금 증거로 바로 지원',
      summary: '전공·Python·ATT&CK 이해를 정리해 디에스앤텍에 바로 지원하는 경로예요.',
      confirmed: ['정보보호 전공', 'Python 스크립트'], missing: ['Linux·로그분석 실무'],
      hardRisk: false, effort: 'low', deliverable: null,
      benefits: ['신입 지원 가능', '전공·자격이 잘 맞음'], risks: ['로그분석 실무 증거가 얇음'],
      relatedPostings: [],
      applyGuide: {
        matches: [
          { requirement: '정보보호 전공·보안 지식', evidence: '세종대 정보보호학과', angle: '전공 기본기로 신입 지원 적합성 보이기' },
          { requirement: 'Python 스크립트', evidence: 'Python 보유', angle: '로그 처리·자동화에 쓸 수 있음을 어필' },
          { requirement: 'Linux·로그분석 실무', evidence: '(선택 자료에서 미확인)', angle: '학습 수준을 정직하게 + 배우려는 태도' },
        ],
        checklist: [
          '신입 지원 가능 공고임을 활용했는가',
          '전공·자격 매칭을 앞세웠는가',
          '지원서에 결과물 링크가 연결돼 있는가',
        ],
      },
    },
    {
      id: 'reinforce', kind: 'reinforce', title: '로그분석 산출물 만들고 지원',
      summary: 'ELK로 로그 수집·분석 실습 산출물을 만들어 핵심 격차를 메운 뒤 지원하는 경로예요.',
      confirmed: ['정보보호 전공', 'Python 스크립트'], missing: ['Linux·로그분석 실무'],
      hardRisk: false, effort: 'mid', deliverable: 'ELK로 EDR 로그 탐지룰 만들기',
      benefits: ['topGap을 정확히 겨냥', '실무형 증거 확보'], risks: ['1~2주 준비 필요'],
      relatedPostings: [],
    },
  ],
  alternatives: [],
};

const HYUNDAI_CONTEXT = {
  company: '㈜현대퓨처넷', role: '정보보안 (신입)', career: '신입',
  stack: ['보안성 검토', '보안솔루션 운영', 'ISMS 대응', '관리·기술·물리 보안', '4년제 학사'],
};
const HYUNDAI_QUESTIONS = [
  { questionId: 'h1', field: 'isms', text: 'ISMS 같은 보안인증(정보보호 관리체계) 대응 업무를 접해본 적 있나요?',
    options: ['있음', '공부만', '처음'], followup: '보안인증 지식 수준을 로드맵에 반영할게요.' },
  { questionId: 'h2', field: 'major', text: '정보보호 전공에서 관리·기술·물리 보안을 폭넓게 배우셨나요?',
    options: ['네', '일부', '개발 위주였음'], followup: '전공 강점을 준비도에 반영했어요.' },
  { questionId: 'h3', field: 'direction', text: '실시간 대응보다 정책·검토·인증 중심 업무도 잘 맞으실까요?',
    options: ['좋아요', '상관없음', '실무 선호'], followup: '업무 방향 선호를 참고했어요.' },
];
const HYUNDAI_RESULT = {
  readiness: { now: 70, goal: 88, topGap: '관리보안(ISMS) 실무 지식', judge: '자격·전공이 잘 맞아 지금 바로 지원 가능 · 관리보안이라 실시간 실무와는 결이 다름' },
  roadmap: [
    { no: 1, title: 'ISMS-P 통제항목 학습', meta: '관리체계 인증 기준 이해', delta: '+8', status: 'active' },
    { no: 2, title: '보안성 검토 체크리스트 실습', meta: '관리·기술·물리 보안 점검표 작성', delta: '+6', status: 'locked' },
    { no: 3, title: '정보보안기사 필기', meta: '관리보안 영역 강함', delta: '+4', status: 'locked' },
  ],
  gaps: [
    { requirement: '보안인증(ISMS) 실무 지식', mark: 'tri', fix: 'ISMS-P 통제항목 학습' },
    { requirement: '관리·기술·물리 보안 검토', mark: 'tri', fix: '보안성 검토 체크리스트' },
    { requirement: '정보보호 전공', mark: 'ok', evidence: '세종대 정보보호학과' },
    { requirement: '4년제 학사 자격', mark: 'ok', evidence: '세종대 졸업' },
    { requirement: '즉시 근무 가능', mark: 'ok', evidence: '가능' },
    { requirement: '실무 경험', mark: 'tri', fix: '프로젝트·인턴으로 보완' },
  ],
  artifact: { title: '정보보호 전공 프로젝트를 관리보안 관점으로 재정리' },
  routes: [
    {
      id: 'as_is', kind: 'as_is', title: '지금 바로 지원',
      summary: '전공·자격 요건이 잘 맞아 곧바로 지원하는 경로예요.',
      confirmed: ['정보보호 전공', '4년제 학사'], missing: ['ISMS 실무 지식'],
      hardRisk: false, effort: 'low', deliverable: null,
      benefits: ['자격·전공이 잘 맞음', '즉시 지원 가능'], risks: ['관리보안 실무 증거는 얇음'],
      relatedPostings: [],
      applyGuide: {
        matches: [
          { requirement: '정보보호 전공', evidence: '세종대 정보보호학과', angle: '관리·기술·물리 보안을 폭넓게 배운 점 강조' },
          { requirement: '4년제 학사 자격', evidence: '세종대 졸업', angle: '지원 자격 충족을 명확히' },
          { requirement: 'ISMS 실무 지식', evidence: '(선택 자료에서 미확인)', angle: '학습 의지 + 전공 연결로 서술' },
        ],
        checklist: [
          '자격 요건 충족을 확인했는가',
          '전공을 관리보안 관점으로 정리했는가',
          '즉시 근무 가능함을 강조했는가',
        ],
      },
    },
    {
      id: 'reinforce', kind: 'reinforce', title: '관리보안 관점 정리 후 지원',
      summary: '전공 프로젝트를 관리보안(ISMS) 관점으로 재정리해 강점을 또렷하게 만든 뒤 지원하는 경로예요.',
      confirmed: ['정보보호 전공', '4년제 학사'], missing: ['ISMS 실무 지식'],
      hardRisk: false, effort: 'mid', deliverable: '정보보호 전공 프로젝트를 관리보안 관점으로 재정리',
      benefits: ['관리보안 강점을 또렷하게', '면접 대비'], risks: ['재정리에 시간 소요'],
      relatedPostings: [],
    },
  ],
  alternatives: [],
};

// 공고 → 시나리오 선택 (시연 큐레이팅 우선, 아니면 일반 폴백)
function pickScenario(rawJob) {
  if (isShieldPosting(rawJob)) return { name: 'shield', ctx: SHIELD_CONTEXT, questions: SHIELD_QUESTIONS, result: SHIELD_RESULT };
  if (isDsntech(rawJob)) return { name: 'dsntech', ctx: DSNTECH_CONTEXT, questions: DSNTECH_QUESTIONS, result: DSNTECH_RESULT };
  if (isHyundai(rawJob)) return { name: 'hyundai', ctx: HYUNDAI_CONTEXT, questions: HYUNDAI_QUESTIONS, result: HYUNDAI_RESULT };
  return { name: 'generic', ctx: parseJob(rawJob), questions: GENERIC_QUESTIONS, result: RESULT };
}

/* ============================================================
   로드맵 생성(저장) — 웹의 POST /roadmap. (회사 + 경로유형 + 목표 맥락)으로 로드맵을 정리한다.
   goalCompany(목표 맥락)이 있으면 "디딤돌" 로드맵 — 그 목표로 잇는 스텝·연결문이 추가돼 내용이 달라진다.
   ============================================================ */
function scenarioResultByCompany(company) {
  const c = String(company || '');
  if (/쉴드원/.test(c)) return SHIELD_RESULT;
  if (/디에스앤텍/.test(c)) return DSNTECH_RESULT;
  if (/현대퓨처넷/.test(c)) return HYUNDAI_RESULT;
  return RESULT;
}

function generateRoadmap(input) {
  const company = String((input && input.company) || '이 공고');
  const routeKind = input && input.routeKind === 'as_is' ? 'as_is' : 'reinforce';
  const goalCompany = input && input.goalCompany ? String(input.goalCompany) : null;
  const base = scenarioResultByCompany(input && input.company);

  let title, intro, steps;
  if (routeKind === 'reinforce') {
    steps = (base.roadmap || []).map((s) => ({ no: s.no, title: s.title, meta: s.meta }));
    title = company + ' · 보강 후 지원 로드맵';
    intro = (base.readiness && base.readiness.topGap ? base.readiness.topGap : '핵심 격차') +
      '을(를) 보완해 지원 경쟁력을 높이는 준비 경로예요.';
  } else {
    steps = [
      { no: 1, title: '선택한 증거를 공고 요건에 맞춰 재정리', meta: '요구사항별 매칭 정리' },
      { no: 2, title: '이력서·포트폴리오 다듬기', meta: '결과물 링크 연결' },
      { no: 3, title: '지원 및 회고 기록', meta: '실제 소요시간 기록' },
    ];
    title = company + ' · 지금 지원 로드맵';
    intro = '현재 가진 증거를 정리해 바로 지원하는 준비 경로예요.';
  }

  let goalLink = null;
  if (goalCompany) {
    goalLink = company + '에서 실무를 쌓아 → ' + goalCompany + '으로 잇는 디딤돌 경로예요. ' +
      '여기서 얻는 경험이 ' + goalCompany + ' 요건으로 이어져요.';
    steps = steps.concat([{
      no: steps.length + 1,
      title: goalCompany + ' 재지원 준비',
      meta: '축적한 실무 경험을 ' + goalCompany + ' 요건에 매핑',
    }]);
    title = title + ' (→ ' + goalCompany + ' 디딤돌)';
  }

  return { title, intro, steps, goalLink };
}

// 하서진 이력서 감지 → 큐레이팅된 13개 조각
const HASEOJIN_MARKERS = /하서진|0xARMOURY|정보보호학과|SSAFY\s*15\s*기|KISIA/i;
const HASEOJIN_FRAGMENTS = [
  { kind: 'STACK', label: 'Java', description: '' },
  { kind: 'STACK', label: 'Spring Boot', description: '' },
  { kind: 'STACK', label: 'MySQL', description: '' },
  { kind: 'STACK', label: 'JavaScript', description: '' },
  { kind: 'STACK', label: 'Vue', description: '' },
  { kind: 'STACK', label: 'React', description: '' },
  { kind: 'STACK', label: 'Python', description: '' },
  { kind: 'STACK', label: 'Git', description: '' },
  { kind: 'PROJECT', label: '0xARMOURY', description: 'MITRE ATT&CK 기반 졸업프로젝트' },
  { kind: 'PROJECT', label: 'Claude API 파일 분석', description: 'AI 활용 파일 분석 프로젝트' },
  { kind: 'EDU', label: '세종대학교 정보보호학과', description: '졸업 · 정보보호 전공' },
  { kind: 'EDU', label: 'KISIA AI보안 기술개발 교육과정', description: '수료' },
  { kind: 'EDU', label: 'SSAFY 15기', description: '웹 개발 학습 중' },
];

/* ── 저장소 자료 파편화 (원샷) ── */
function extractEvidence(sourceType, content) {
  if (HASEOJIN_MARKERS.test(String(content))) {
    return HASEOJIN_FRAGMENTS.map((f) => ({ ...f }));
  }
  return genericExtract(String(content || ''));
}

function genericExtract(content) {
  const out = [];
  for (const s of scanStacks(content)) out.push({ kind: 'STACK', label: s, description: '' });

  const GH = /github\.com\/([\w.-]+)\/([\w.-]+)/gi;
  let m;
  while ((m = GH.exec(content))) {
    out.push({ kind: 'GITHUB', label: m[2].replace(/\.git$/, ''), description: `GitHub · ${m[1]}/${m[2].replace(/\.git$/, '')}` });
  }

  let projCount = 0;
  for (const rawLine of content.split(/\r?\n/)) {
    const t = rawLine.trim();
    if (t.length < 4 || t.length > 120) continue;
    if (/자격증|기사|SQLD|SQLP|정보처리|정보보안|ADsP|TOEIC|OPIc|HSK/i.test(t)) {
      out.push({ kind: 'CERT', label: trimLabel(t), description: '자격/시험' });
    } else if (/대학교|대학원|학과|전공|학사|석사|부트캠프|SSAFY|싸피|교육과정|수료/i.test(t)) {
      out.push({ kind: 'EDU', label: trimLabel(t), description: '교육/학력' });
    } else if (projCount < 6 && /프로젝트|개발|구축|설계|서비스|시스템|플랫폼|\bAPI\b|앱/i.test(t)) {
      out.push({ kind: 'PROJECT', label: trimLabel(t), description: '프로젝트 경험' });
      projCount++;
    }
  }
  return out;
}

function trimLabel(line) {
  const s = line.replace(/^[\-*•·\d.)\s]+/, '').trim();
  return s.length > 60 ? s.slice(0, 60).trim() + '…' : s;
}

/* ============================================================
   일반 입력용 휴리스틱 (시연 외 공고/자료 폴백)
   ============================================================ */
const GENERIC_QUESTIONS = [
  {
    questionId: 'q1', field: 'performance_metric',
    text: '성능 개선처럼 측정 가능한 수치 경험이 있나요?',
    options: ['있음', '측정 안 해봤어요'],
    followup: '성과 근거로 반영해 분석을 이어갈게요.',
  },
];

const STACKS = [
  ['Spring Boot', /spring\s*boot/i], ['Spring Security', /spring\s*security/i],
  ['Spring Batch', /spring\s*batch/i], ['Spring', /\bspring\b/i],
  ['JPA', /\bjpa\b|hibernate|querydsl/i], ['Java', /\bjava\b/i], ['Kotlin', /\bkotlin\b/i],
  ['Python', /\bpython\b/i], ['Django', /\bdjango\b/i], ['FastAPI', /fast\s*api/i],
  ['Node.js', /node\.?\s*js|nodejs/i], ['Express', /\bexpress\b/i],
  ['TypeScript', /type\s*script|\bts\b/i], ['JavaScript', /java\s*script|\bjs\b/i],
  ['React', /\breact\b/i], ['Next.js', /next\.?\s*js/i], ['Vue', /\bvue\b/i],
  ['MySQL', /\bmysql\b|maria\s*db/i], ['PostgreSQL', /postgre\s*sql|\bpostgres\b/i],
  ['Oracle', /\boracle\b/i], ['MongoDB', /mongo\s*db|\bmongo\b/i], ['Redis', /\bredis\b/i],
  ['Elasticsearch', /elastic\s*search|\belk\b/i], ['Kafka', /\bkafka\b/i], ['RabbitMQ', /rabbit\s*mq/i],
  ['Docker', /\bdocker\b/i], ['Kubernetes', /kubernetes|\bk8s\b/i],
  ['AWS', /\baws\b|amazon\s*web/i], ['GCP', /\bgcp\b|google\s*cloud/i], ['Nginx', /\bnginx\b/i],
  ['Jenkins', /\bjenkins\b/i], ['GitHub Actions', /github\s*actions/i], ['Terraform', /\bterraform\b/i],
  ['GraphQL', /graph\s*ql/i], ['gRPC', /\bgrpc\b/i], ['Gradle', /\bgradle\b/i], ['JUnit', /\bjunit\b/i],
];
const CAREER = /(신입|경력\s*무관|경력무관|무관|주니어|시니어|\d+\s*년\s*(이상|↑|차)?)/i;
const ROLE = /(백엔드|프론트\s*엔드|프론트엔드|풀\s*스택|풀스택|서버|안드로이드|iOS|데이터\s*(엔지니어|분석가)?|머신\s*러닝|\bML\b|\bAI\b|DevOps|데브옵스|인프라|보안|\bQA\b|기획|디자이너|\bPM\b|개발자|엔지니어|Engineer|Developer)/i;

function scanStacks(text) {
  let work = String(text || '');
  const found = [];
  for (const [label, re] of STACKS) {
    if (re.test(work)) { found.push(label); work = work.replace(new RegExp(re.source, 'gi'), ' '); }
  }
  return found;
}

function parseJob(raw) {
  const content = String(raw || '').trim();
  const stack = scanStacks(content);
  let career = (content.match(CAREER) || [null])[0];
  career = career ? career.replace(/\s+/g, '') : '경력무관';

  let company = '채용 공고', role = '';
  const urlOnly = /^https?:\/\/\S+$/i.test(content);
  if (urlOnly) {
    const host = content.match(/^https?:\/\/(?:www\.)?([^/\s]+)/i);
    company = host ? host[1] : '채용 공고';
    role = (content.match(ROLE) || [''])[0];
  } else {
    const firstLine = (content.split(/\r?\n/).find((l) => l.trim().length >= 2) || content).trim();
    const parts = firstLine.split(/[·|/\-–—\t]+/).map((s) => s.trim()).filter(Boolean);
    company = (parts[0] || '')
      .replace(/\[.*?\]/g, '').replace(/\(주\)|주식회사|㈜/g, '').replace(/(채용|공고|모집|공채|수시)$/g, '').trim() || '채용 공고';
    role = (firstLine.match(ROLE) || [])[0] || (content.match(ROLE) || [])[0] || parts[1] || '';
  }
  return { company: company.slice(0, 100), role: (role || '').slice(0, 150), career: career.slice(0, 50), stack };
}
