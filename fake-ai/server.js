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
    req.setEncoding('utf8');   // 멀티바이트(한글)가 청크 경계에 걸쳐 깨지지 않게
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
    req.setEncoding('utf8');   // 멀티바이트(한글)가 청크 경계에 걸쳐 깨지지 않게
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
  if (req.method === 'POST' && req.url === '/reassess') {
    let body = '';
    req.setEncoding('utf8');   // 멀티바이트(한글)가 청크 경계에 걸쳐 깨지지 않게
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      let payload = {};
      try { payload = JSON.parse(body || '{}'); } catch (e) {}
      const verdict = generateReassess(payload);
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(verdict));
      const st = (payload.step && (payload.step.no || payload.step.title)) || '?';
      console.log(`  [HTTP] /reassess → step ${st} : ${verdict.verdict}`);
    });
    return;
  }
  if (req.method === 'POST' && req.url === '/roadmap-ask') {
    let body = '';
    req.setEncoding('utf8');   // 멀티바이트(한글)가 청크 경계에 걸쳐 깨지지 않게
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      let payload = {};
      try { payload = JSON.parse(body || '{}'); } catch (e) {}
      const out = generateAsk(payload);
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(out));
      console.log(`  [HTTP] /roadmap-ask → "${String(payload.question || '').slice(0, 30)}"`);
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
  decision: {
    status: 'MID_TERM_TARGET', label: '중기 목표',
    headline: '지금 직접 지원보다 중기 목표로 두는 게 현실적이에요.',
    reasons: [
      '공고가 "경력 1년 이상(신입 불가)"를 필수로 명시했어요.',
      '현재 자료에서는 해당 실무 경력을 확인하지 못했어요.',
      '경력 요건은 다른 스택·프로젝트를 늘려도 대체되지 않는 조건이에요.',
    ],
    hardConstraints: [
      { requirement: '경력 1년 이상 (신입 불가)', current: '실무 경력 미확인', substitutableByProject: false },
    ],
    nextTarget: '신입 지원이 가능한 보안·EDR 유사 직무에서 실무 경력 쌓기',
    recheckCondition: '실무 경력 1년+ 확보 후 이 공고(또는 유사 공고) 재분석',
  },
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
      summary: '지금 지원 가능한 관련 공고를 함께 보며 EDR 실무 경력 자체를 쌓는 경로예요.',
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
      label: '관련 공고', reason: '보안솔루션 구축·로그 분석 실무를 직접 쌓을 수 있는 곳',
      rawText: 'https://www.jobkorea.co.kr/Recruit/GI_Read/49585116?Oem_Code=C1&logpath=1&stext=EDR&listno=13&sc=630',
    },
    {
      id: 'hyundai', company: '㈜현대퓨처넷', role: '정보보안 (신입)', career: '신입',
      label: '관련 공고', reason: '지금 바로 지원 가능 · 정보보안 전공/교육 우대와 매칭',
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
  decision: {
    status: 'APPLY_WITH_POLISH', label: '지원하되 보완 권장',
    headline: '지금 지원할 수 있어요. 로그분석 증거를 보완하면 경쟁력이 올라가요.',
    reasons: [
      '공고가 "신입~6년"이라 신입 지원이 가능해, 필수 경력과의 충돌이 없어요.',
      '정보보호 전공·Python 등 기본기는 이미 확인됐어요.',
      'Linux 운영·로그분석 실무 증거는 아직 얇지만, 산출물로 단기간에 메울 수 있어요.',
    ],
    hardConstraints: [],
    nextTarget: null,
    recheckCondition: '로그분석 산출물 1개 완료 후 지원 자료에 연결해 재점검',
  },
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
  decision: {
    status: 'APPLY_NOW', label: '지금 지원 가능',
    headline: '전공·자격 요건이 잘 맞아 지금 지원할 수 있어요.',
    reasons: [
      '공고가 요구하는 신입·정보보호 전공·4년제 학사를 모두 충족해요.',
      '명시된 필수조건과의 충돌이 없어요.',
      'ISMS 등 관리보안 실무는 우대라, 관점을 정리해두면 차별화돼요.',
    ],
    hardConstraints: [],
    nextTarget: null,
    recheckCondition: null,
  },
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
   로드맵 생성(저장) — 웹의 POST /roadmap. (회사 + 경로유형)으로 리치 로드맵을 내준다.
   (b) 결정: 목표 맥락으로 내용을 바꾸지 않는다(디딤돌 변형 없음). 6개(3사×즉시/보강) 큐레이팅.
   스텝 철학: 격차(왜) → 만들 산출물(증거) → 완료 기준 + 참고(학습 키워드·리소스는 접기). 단정 금지.
   ============================================================ */
const HJ_STRENGTHS = ['정보보호 전공(세종대)', '0xARMOURY · MITRE ATT&CK', 'Python'];

const CURATED_ROADMAPS = {
  shield: {
    reinforce: {
      title: '㈜쉴드원 · 보강 후 지원 로드맵', topGap: 'EDR · 엔드포인트 실무',
      intro: 'EDR 실무 증거를 만들어 지원 경쟁력을 높이는 준비 경로예요.',
      targetDate: '2026-08-31',
      today: ['Wazuh Docker 컨테이너 올리기', '엔드포인트 VM 1대 에이전트 등록', '의심 행위 1개 탐지룰 초안 잡기'],
      steps: [
        { no: 1, title: '오픈소스 EDR 실습', duration: '2–3주', difficulty: '중', meta: 'Wazuh로 엔드포인트 로그·탐지룰',
          requirement: 'EDR·엔드포인트 솔루션 실무',
          quote: '공고 자격요건: "EDR·엔드포인트 보안 솔루션 운영 경험"',
          gap: '필수 "EDR·엔드포인트 솔루션 실무"가 현재 자료에서 미확인이에요.',
          artifact: 'Wazuh로 엔드포인트의 의심 행위를 탐지하는 커스텀 룰 + 운영 리포트 (GitHub)',
          done: '에이전트 등록 · 탐지 발생 로그 · 룰 파일 · 3줄 회고',
          hint: 'Wazuh를 Docker로 올리고 엔드포인트 1대(예: Ubuntu VM)를 에이전트로 등록 → 의심 행위(새 사용자 추가·권한 상승)를 일으켜 커스텀 룰로 탐지 → 발생 로그와 룰 파일을 GitHub에 정리해요.',
          pitfall: '에이전트는 연결됐는데 이벤트가 안 뜨는 경우, 대부분 방화벽/포트(1514·1515)와 시간 동기화(NTP) 문제예요.',
          keywords: ['Wazuh', '엔드포인트 로그', '파일 무결성'], resources: ['Wazuh 설치 가이드', '샘플 공격 시나리오'],
          verifyHints: ['wazuh', 'edr', 'endpoint', '탐지룰', 'detection'] },
        { no: 2, title: '공격→탐지 잇기 (0xARMOURY 재활용)', duration: '2주', difficulty: '중상', meta: 'ATT&CK 시나리오를 탐지룰로',
          requirement: '탐지 관점(ATT&CK) 증거',
          quote: '공고: "악성코드 분석·침해대응 및 MITRE ATT&CK 이해"',
          gap: '공격 관점(0xARMOURY)은 있으나 "탐지 관점" 증거가 없어요.',
          artifact: '0xARMOURY의 ATT&CK 기법 하나를 탐지하는 룰 + 탐지 리포트',
          done: '공격 재현 → 탐지 캡처 → 기법 매핑 문서',
          keywords: ['MITRE ATT&CK', '탐지 엔지니어링'], resources: ['ATT&CK Navigator'],
          verifyHints: ['attack', 'mitre', 'detection', 'navigator', '0xarmoury'] },
        { no: 3, title: '정보보안기사 필기', duration: '병행', difficulty: '하', meta: '전공 배경 활용',
          requirement: '정보보안기사(우대)',
          quote: '공고 우대: "정보보안기사 등 보안 자격증 보유"',
          gap: '우대 "정보보안기사"가 아직 없어요 (필수 아님).',
          artifact: '필기 접수 완료 또는 학습 계획',
          done: '접수 · 학습 일정', keywords: ['정보보안기사'], resources: ['시험 일정'],
          verifyHints: ['정보보안기사', 'sisa', 'q-net', 'qnet', 'cert', 'study'] },
      ],
    },
    as_is: {
      title: '㈜쉴드원 · 지금 지원 로드맵', topGap: 'EDR 실무 (지원 자료로 보완)',
      intro: '지금 가진 증거를 EDR 관점으로 정리해 곧바로 지원하는 준비 경로예요.',
      steps: [
        { no: 1, title: "0xARMOURY를 'EDR 탐지 관점'으로 재정리", duration: '3–4일', difficulty: '하', meta: '공격 프로젝트를 탐지 언어로',
          requirement: '탐지 관점 서술 증거',
          gap: '프로젝트가 "공격" 서술이라 EDR(탐지) 직무와 연결이 약해요.',
          artifact: "0xARMOURY README를 '이 공격을 어떻게 탐지하나' 관점으로 재작성",
          done: '탐지 관점 문단 추가 · 결과물 링크 정리', keywords: ['탐지 관점 서술'], resources: [],
          verifyHints: ['0xarmoury', 'readme', 'detection', 'portfolio'] },
        { no: 2, title: '경력 필수조건 대응 정리', duration: '2일', difficulty: '하', meta: '숨기지 않는 서술 전략',
          requirement: '경력 조건 서술 전략',
          gap: '필수 "경력 1년↑"과 충돌해요 — 숨기지 말고 어떻게 다룰지 정해요.',
          artifact: '교육·프로젝트로 실무 근접함을 보이는 지원 문단',
          done: '충돌 조건에 대한 솔직한 서술 준비', keywords: [], resources: [],
          verifyHints: ['cover', 'letter', 'resume', '자소서', 'cv'] },
        { no: 3, title: '지원 + 회고', duration: '1일', difficulty: '하', meta: '실제 소요시간 기록',
          requirement: '지원 완료',
          gap: '정리한 자료로 지원해요.', artifact: '지원 완료 + 무엇을 어필했는지 회고',
          done: '지원 링크 · 회고', keywords: [], resources: [],
          verifyHints: ['apply', 'application', 'review', 'retro', '회고'] },
      ],
    },
  },
  dsntech: {
    reinforce: {
      title: '㈜디에스앤텍 · 보강 후 지원 로드맵', topGap: 'Linux · 로그분석 실무',
      intro: 'Linux·로그분석 실무 증거를 만들어 지원하는 준비 경로예요.',
      targetDate: '2026-08-31',
      today: ['Ubuntu VM에 SSH 서버 띄우기', 'auth.log 구조 훑기', '실패 로그인 IP 집계 스크립트 시작'],
      steps: [
        { no: 1, title: '로그 분석 실무 증거', duration: '2–3주', difficulty: '중', meta: 'ELK로 로그 수집·탐지',
          requirement: 'Linux 운영·로그 분석',
          quote: '공고 자격요건: "Linux 서버 운영 및 보안장비(방화벽·EDR) 로그 분석 경험"',
          gap: '필수 "Linux 운영·로그 분석"이 현재 자료에서 미확인이에요.',
          artifact: 'ELK로 SSH 무차별대입 시도를 탐지하는 대시보드 + 탐지룰 (GitHub)',
          done: '실제 로그 유입 · 탐지 동작 · GitHub 링크 · 3줄 회고',
          hint: 'Ubuntu VM에 SSH 서버를 띄우고 auth.log를 Filebeat→ELK로 수집 → 실패 로그인 IP를 집계하는 Kibana 대시보드와 임계치 탐지룰을 만들어 GitHub에 올려요.',
          pitfall: '로그 타임존 불일치로 대시보드 시간축이 어긋나는 게 가장 흔해요. Logstash에서 @timestamp를 UTC로 통일하세요.',
          keywords: ['auth.log', 'ELK', 'KQL'], resources: ['Docker compose 예시', '샘플 로그셋'],
          verifyHints: ['elk', 'kibana', 'logstash', 'filebeat', 'auth.log', 'elastic', 'kql', 'ssh'] },
        { no: 2, title: '보안솔루션 운영 증거 (Wazuh)', duration: '3–4주', difficulty: '상', meta: '오픈소스 EDR/SIEM 운영',
          requirement: '보안솔루션(EDR/SIEM) 운영',
          quote: '공고 우대: "EDR·SIEM 등 보안솔루션 구축·운영 경험"',
          gap: '"EDR·SIEM 구축·운영" 증거가 없어요.',
          artifact: 'Wazuh 설치·엔드포인트 등록 후 탐지룰 1개 + 운영 리포트',
          done: '에이전트 등록 · 탐지 발생 · 룰 파일',
          hint: '1단계에서 만든 로그 환경 위에 Wazuh 매니저를 올리고 엔드포인트를 에이전트로 등록 → ATT&CK 기법 하나를 탐지하는 룰을 추가하고 운영 리포트를 남겨요.',
          keywords: ['Wazuh', 'SIEM', 'ATT&CK 매핑'], resources: ['Wazuh 문서'],
          verifyHints: ['wazuh', 'siem', 'edr', 'detection', 'mitre'] },
        { no: 3, title: '지원 준비', duration: '1주', difficulty: '하', meta: '포트폴리오 정리',
          requirement: '포트폴리오 정리',
          quote: '공고: "관련 프로젝트·포트폴리오 제출"',
          gap: '만든 산출물을 지원 자료로 묶고 마지막으로 점검해요.',
          artifact: '산출물 2개를 담은 포트폴리오 + 요건 대비표',
          done: '포트폴리오 링크 · 대비표', keywords: [], resources: [],
          verifyHints: ['portfolio', '포트폴리오', 'report', '대비표'] },
      ],
    },
    as_is: {
      title: '㈜디에스앤텍 · 지금 지원 로드맵', topGap: '로그분석 실무 (지원 자료로 보완)',
      intro: '전공·Python·ATT&CK 이해를 정리해 바로 지원하는 준비 경로예요.',
      steps: [
        { no: 1, title: '전공·Python을 직무 언어로 정리', duration: '3–4일', difficulty: '하', meta: '요건 매칭 정리',
          requirement: '요건×증거 매칭',
          gap: '신입 지원 가능 공고예요 — 전공·Python이 어느 요건에 맞는지 정리가 필요해요.',
          artifact: '요구사항별로 내 증거를 매칭한 지원 자료 초안',
          done: '요건×증거 매칭표 · 어필 포인트', keywords: [], resources: [],
          verifyHints: ['match', '매칭', '대비표', 'portfolio', 'resume'] },
        { no: 2, title: '로그분석 학습 의지 보이기', duration: '2일', difficulty: '하', meta: '작은 실습 하나',
          requirement: '로그 파싱 실습 증거',
          gap: '로그분석 실무 증거는 얇아요 — 배우려는 태도를 작은 결과물로 보여요.',
          artifact: '간단한 로그 파싱 스크립트 1개 (Python)',
          done: '스크립트 · GitHub 링크', keywords: ['로그 파싱'], resources: [],
          verifyHints: ['parse', '파싱', 'logparser', 'python', 'script'] },
        { no: 3, title: '지원 + 회고', duration: '1일', difficulty: '하', meta: '',
          requirement: '지원 완료',
          gap: '정리한 자료로 지원해요.', artifact: '지원 완료 + 회고', done: '지원 링크 · 회고', keywords: [], resources: [],
          verifyHints: ['apply', 'application', 'review', 'retro', '회고'] },
      ],
    },
  },
  hyundai: {
    reinforce: {
      title: '㈜현대퓨처넷 · 보강 후 지원 로드맵', topGap: '관리보안(ISMS) 실무 지식',
      intro: '관리보안(ISMS) 지식을 전공 강점과 이어 지원하는 준비 경로예요.',
      steps: [
        { no: 1, title: 'ISMS-P 통제항목 학습', duration: '2주', difficulty: '중', meta: '관리체계 인증 기준',
          requirement: '보안인증(ISMS) 지식',
          gap: '"보안인증(ISMS) 대응" 지식이 현재 자료에서 미확인이에요.',
          artifact: 'ISMS-P 통제항목을 내 언어로 정리한 노트 (공개 글/문서)',
          done: '핵심 통제항목 요약 · 이해 확인', keywords: ['ISMS-P', '관리체계'], resources: ['ISMS-P 인증기준'],
          verifyHints: ['isms', 'ismsp', '통제항목', 'cert', 'study'] },
        { no: 2, title: '전공 프로젝트를 관리보안 관점으로 재정리', duration: '1주', difficulty: '하', meta: '기술→관리 관점 전환',
          requirement: '관리보안 관점 증거',
          gap: '전공 강점을 관리·기술·물리 보안 관점으로 연결한 증거가 필요해요.',
          artifact: '기존 전공 프로젝트를 관리보안 관점으로 재정리한 문서',
          done: '관점 전환 문서 · 링크', keywords: ['보안성 검토', '관리·기술·물리'], resources: [],
          verifyHints: ['관리보안', 'governance', 'review', 'security'] },
        { no: 3, title: '정보보안기사 필기', duration: '병행', difficulty: '하', meta: '관리보안 영역 강함',
          requirement: '정보보안기사(우대)',
          gap: '우대 자격이에요 (필수 아님).', artifact: '필기 접수/학습 계획',
          done: '접수 · 학습 일정', keywords: ['정보보안기사'], resources: [],
          verifyHints: ['정보보안기사', 'sisa', 'q-net', 'qnet', 'cert', 'study'] },
      ],
    },
    as_is: {
      title: '㈜현대퓨처넷 · 지금 지원 로드맵', topGap: 'ISMS 실무 (지원 자료로 보완)',
      intro: '전공·자격 요건이 잘 맞아 곧바로 지원하는 준비 경로예요.',
      steps: [
        { no: 1, title: '자격 요건 충족 확인·강조', duration: '2일', difficulty: '하', meta: '전공·학사 매칭',
          requirement: '자격 요건 정리',
          gap: '신입·전공·4년제 학사 요건이 맞아요 — 이를 앞세워 정리해요.',
          artifact: '자격 충족을 명확히 한 지원 자료', done: '요건 대비표', keywords: [], resources: [],
          verifyHints: ['requirement', '대비표', 'resume', 'checklist'] },
        { no: 2, title: '전공을 관리보안 관점으로 한 문단', duration: '2일', difficulty: '하', meta: '차별화 포인트',
          requirement: '관리보안 관점 서술',
          gap: '관리보안 관점 서술이 있으면 다른 지원자와 차별화돼요.',
          artifact: '전공 경험을 관리보안 관점으로 요약한 자기소개 문단',
          done: '문단 · 근거 링크', keywords: [], resources: [],
          verifyHints: ['관리보안', 'cover', 'letter', '자소서'] },
        { no: 3, title: '지원 + 회고', duration: '1일', difficulty: '하', meta: '',
          requirement: '지원 완료',
          gap: '정리한 자료로 지원해요.', artifact: '지원 완료 + 회고', done: '지원 링크 · 회고', keywords: [], resources: [],
          verifyHints: ['apply', 'application', 'review', 'retro', '회고'] },
      ],
    },
  },
};

function scenarioKey(company) {
  const c = String(company || '');
  if (/쉴드원/.test(c)) return 'shield';
  if (/디에스앤텍/.test(c)) return 'dsntech';
  if (/현대퓨처넷/.test(c)) return 'hyundai';
  return null;
}

function generateRoadmap(input) {
  const company = String((input && input.company) || '이 공고');
  const routeKind = input && input.routeKind === 'as_is' ? 'as_is' : 'reinforce';
  const key = scenarioKey(input && input.company);
  const curated = key && CURATED_ROADMAPS[key] && CURATED_ROADMAPS[key][routeKind];
  if (curated) {
    return { title: curated.title, intro: curated.intro, topGap: curated.topGap,
      strengths: HJ_STRENGTHS, steps: curated.steps, goalLink: null,
      targetDate: curated.targetDate || null, today: curated.today || null };
  }
  // 일반 폴백(시연 외) — 리치 필드 최소만
  const rk = routeKind === 'as_is' ? '지금 지원' : '보강 후 지원';
  return {
    title: company + ' · ' + rk + ' 로드맵', topGap: '', strengths: [], goalLink: null,
    intro: routeKind === 'as_is' ? '현재 가진 증거를 정리해 바로 지원하는 준비 경로예요.'
      : '핵심 격차를 보완해 지원 경쟁력을 높이는 준비 경로예요.',
    steps: [
      { no: 1, title: '선택한 증거를 공고 요건에 맞춰 재정리', duration: '3–4일', difficulty: '하', meta: '요구사항별 매칭',
        requirement: '요건×증거 매칭',
        gap: '공고 요건과 내 증거를 맞춰 정리해요.', artifact: '요건×증거 매칭 자료', done: '매칭표', keywords: [], resources: [],
        verifyHints: ['match', '매칭', '대비표', 'portfolio', 'resume'] },
      { no: 2, title: '부족한 요건을 산출물로 보완', duration: '1–2주', difficulty: '중', meta: '증거 만들기',
        requirement: '부족 요건을 메우는 산출물',
        gap: '미확인 요건을 작은 결과물로 메워요.', artifact: '요건을 증명하는 산출물 1개', done: '산출물 · 링크', keywords: [], resources: [],
        verifyHints: ['project', 'demo', 'report', 'portfolio', 'app'] },
      { no: 3, title: '지원 + 회고', duration: '1일', difficulty: '하', meta: '',
        requirement: '지원 완료',
        gap: '정리한 자료로 지원해요.', artifact: '지원 완료 + 회고', done: '지원 링크 · 회고', keywords: [], resources: [],
        verifyHints: ['apply', 'application', 'review', 'retro', '회고'] },
    ],
  };
}

/* ============================================================
   산출물 제출 → 재진단(웹의 POST /reassess). 데모 링크를 인식해 "요건 충족/보완 필요"를 판정한다.
   웹은 저장된 로드맵의 스텝(요건·verifyHints)과 제출 링크만 넘긴다. 진짜 AI가 붙으면 이 함수만 교체.
   철학: 진짜 평가가 아니라 "이 스텝의 신호가 링크에 보이는가"의 규칙 기반 인식(데모용). 단정 금지.
   ============================================================ */
function generateReassess(input) {
  const step = (input && input.step) || {};
  const url = String((input && input.url) || '').trim();
  const low = url.toLowerCase();
  const requirement = step.requirement || step.title || '이 스텝의 핵심 증거';
  const hints = Array.isArray(step.verifyHints) ? step.verifyHints : [];
  const looksLikeLink =
    /^https?:\/\/[^\s]+\.[^\s]+/.test(low) ||
    /(github\.com|gitlab\.com|vercel\.app|netlify\.app|notion\.(so|site)|tistory\.com|velog\.io|\.dev\b)/.test(low);
  // 내용 토큰 매칭: 짧은 영숫자 토큰(elk·edr·ssh 등)은 단어 경계로 봐서 'velog'⊃'log', '.app' TLD 류의 오탐을 막는다.
  // verifyHints에는 스킴(http)·호스트명(github/notion 등)을 넣지 않는다 — 그런 건 "어디에 올렸나"라 "무엇인가"를 못 가린다.
  const matched = hints.some((h) => {
    const t = String(h).toLowerCase().trim();
    if (!t) return false;
    if (/^[a-z0-9]+$/.test(t) && t.length <= 3) {
      return new RegExp('(^|[^a-z0-9])' + t + '([^a-z0-9]|$)').test(low);
    }
    return low.indexOf(t) >= 0;
  });

  // 1) 링크 형식이 아니거나 비어 있음 → 증거로 인식 못 함
  if (!looksLikeLink) {
    return {
      verdict: 'insufficient', resolvedRequirement: null,
      headline: '아직 제출물을 확인하지 못했어요',
      detail: 'GitHub 저장소나 배포·문서 링크를 붙여주시면 산출물을 근거로 다시 진단할 수 있어요.',
      checks: [
        { label: '제출 링크 형식', ok: false },
        { label: requirement + ' 증거', ok: false },
      ],
      nextHint: '완료 기준: ' + (step.done || '산출물 링크') + ' — 이걸 담은 링크를 제출해 주세요.',
    };
  }
  // 2) 링크는 유효하나 이 스텝의 핵심 신호가 안 보임(힌트가 정의된 경우만 엄격히 본다)
  if (hints.length > 0 && !matched) {
    return {
      verdict: 'insufficient', resolvedRequirement: null,
      headline: '링크는 확인했지만 이 요건의 증거가 약해요',
      detail: '“' + requirement + '”을(를) 보여주는 결과물인지 아직 분명하지 않아요.',
      checks: [
        { label: '제출 링크 형식', ok: true },
        { label: requirement + ' 증거', ok: false },
      ],
      nextHint: step.artifact ? '이런 산출물이면 확실해요: ' + step.artifact : '이 스텝의 산출물을 담은 링크를 제출해 주세요.',
    };
  }
  // 3) 유효 링크 + (핵심 신호 매칭 or 힌트 미정의 폴백) → 요건 충족으로 인식
  return {
    verdict: 'verified', resolvedRequirement: requirement,
    headline: '“' + requirement + '” 증거를 확인했어요',
    detail: '제출한 산출물에서 이 요건을 메우는 근거를 확인했어요. 요건 매트릭스에 반영할게요.',
    checks: [
      { label: '제출 링크 형식', ok: true },
      { label: requirement + ' 증거', ok: true },
      { label: '완료 기준 충족', ok: true },
    ],
    nextHint: null,
  };
}

/* ============================================================
   로드맵에 물어보기(웹의 POST /roadmap-ask). 자유 입력을 키워드로 갈라 canned 답을 낸다(데모 연출).
   진짜 AI가 붙으면 이 함수만 교체. 단정 금지 · 이 로드맵 맥락(topGap·company)만 참조.
   ============================================================ */
function generateAsk(input) {
  const q = String((input && input.question) || '').trim();
  const topGap = String((input && input.topGap) || '핵심 요건');
  const company = String((input && input.company) || '이 공고');
  const low = q.toLowerCase();
  let answer;

  if (!q) {
    answer = '무엇이든 물어보세요 — 예: “2주밖에 없어, 압축해줘”, “가장 큰 격차가 뭐야?”, “쉴드원 준비는 어떻게 이어져?”';
  } else if (/2주|시간|빨리|급|압축|짧|촉박|얼마/.test(q)) {
    answer = '시간이 빠듯하면 ' + topGap + '을(를) 정면으로 메우는 1단계 산출물 하나에 집중하세요. 증거 1개만 있어도 지원 경쟁력이 올라가고, 나머지 단계는 지원 후로 미뤄도 괜찮아요.';
  } else if (/격차|부족|뭐부터|우선|먼저|중요/.test(q)) {
    answer = '지금 가장 큰 격차는 “' + topGap + '”이에요. 위 요건×증거 매트릭스에서 “미확인”으로 남은 부분이고, 1단계 산출물이 이걸 정면으로 겨냥합니다.';
  } else if (/왜|이유|의미|목적/.test(q)) {
    answer = '각 스텝은 ' + company + '의 필수 요건을 “말” 대신 “산출물(증거)”로 바꾸려는 거예요. 그래서 스텝마다 만들 산출물과 완료 기준이 붙어 있어요.';
  } else if (/쉴드원|목표|다음\s*단계|이직|나중|경력|이어/.test(q)) {
    answer = '지금 로드맵으로 쌓은 산출물은 그대로 다음 목표 공고 지원의 근거가 돼요. 여기서 만든 증거가 다음 단계의 “경력·실무”로 이어집니다.';
  } else if (/제출|링크|어떻게|방법|올리/.test(q)) {
    answer = '각 스텝 아래 “제출 → 재진단”에 GitHub·배포·문서 링크를 붙이면, 그 산출물이 요건을 메우는지 판단해 매트릭스를 바로 갱신해요.';
  } else if (/자소서|지원서|어필|포트폴리오|이력서/.test(q)) {
    answer = '완료한 스텝의 산출물 링크를 지원 자료에 그대로 연결하세요. “했다”가 아니라 “이걸 만들었다(링크)”가 가장 강한 어필이에요. 아래 “포트폴리오로 묶기”로 한 번에 정리할 수 있어요.';
  } else {
    answer = '좋은 질문이에요. 이 로드맵은 ' + company + '의 요건을 순서대로 산출물로 메우는 길이고, 핵심 격차는 “' + topGap + '”이에요. 특정 스텝이 궁금하면 그 스텝의 “이 스텝 왜?”도 눌러보세요.';
  }
  return { question: q, answer: answer };
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
