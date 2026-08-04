import {
  BriefcaseBusiness,
  ClipboardCheck,
  Compass,
  Download,
  FileSearch,
  FileUser,
  Heart,
  MessageCircleMore,
  Mic,
  PenLine,
  Route,
  ScanSearch,
  Sparkles,
  type LucideIcon,
} from "@lucide/vue";

/**
 * 에이전트 화자 등록부 — 색과 로고의 **단일 출처**.
 *
 * AI 는 화자 키(agent)와 문구만 보낸다. 색·로고를 AI·백엔드·프론트 세 곳에 두면 갈리므로
 * 화면 자원은 여기 한 곳에만 둔다. 키는 AI 의 `orchestrator/router.py` `_AGENT_LABEL` 과
 * 같은 이름공간이고, `orchestrator` 는 에이전트를 고르는 쪽(플래너·실행 계획)이다.
 *
 * 색은 공고 분석 진행 휠(AI `_analysis_stages`)이 쓰는 팔레트를 이어 쓴다 — 같은 서비스에서
 * 같은 역할이 다른 색으로 보이면 사용자는 다른 담당으로 읽는다.
 */
export type AgentIdentity = {
  label: string;
  color: string;
  icon: LucideIcon;
};

const AGENTS: Record<string, AgentIdentity> = {
  orchestrator: { label: "대화 오케스트레이터", color: "#1cb0f6", icon: Compass },
  posting_analysis: { label: "공고 분석", color: "#ce82ff", icon: FileSearch },
  posting_fetch: { label: "공고 수집", color: "#8b5cf6", icon: Download },
  fit_analysis: { label: "적합도 분석", color: "#2b70c9", icon: ScanSearch },
  application_plan: { label: "지원 경로 설계", color: "#58cc02", icon: Route },
  roadmap_manager: { label: "로드맵 조회", color: "#3aa655", icon: ClipboardCheck },
  job_recommend: { label: "공고 추천", color: "#ff9600", icon: BriefcaseBusiness },
  preference_intake: { label: "선호 파악", color: "#ffc800", icon: Heart },
  resume_diagnosis: { label: "이력서 진단", color: "#ff86d0", icon: FileUser },
  interview_prep: { label: "면접 준비", color: "#ff4b4b", icon: Mic },
  coverletter_draft: { label: "자소서 초안", color: "#e5793a", icon: PenLine },
  career_chat: { label: "진로 대화", color: "#1cb0f6", icon: MessageCircleMore },
};

// 등록부에 없는 키(에이전트가 새로 생겼는데 여기 추가를 잊은 경우)도 **말은 하게 한다**.
// 색은 키에서 결정론으로 뽑는다 — 같은 에이전트가 매번 같은 색으로 보여야 한다.
const FALLBACK_COLORS = ["#1cb0f6", "#ce82ff", "#ff9600", "#58cc02", "#ff86d0", "#2b70c9"];

export function agentIdentity(agent: string | null | undefined): AgentIdentity {
  const key = (agent ?? "").trim();
  const known = AGENTS[key];
  if (known) return known;
  if (!key) return { label: "JOBISS", color: "#1cb0f6", icon: Sparkles };
  let hash = 0;
  for (const char of key) hash = (hash + char.charCodeAt(0)) % FALLBACK_COLORS.length;
  return {
    label: key,
    color: FALLBACK_COLORS[hash],
    icon: Sparkles,
  };
}
