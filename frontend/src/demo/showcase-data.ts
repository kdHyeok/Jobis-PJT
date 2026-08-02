import type { CareerMap, CareerNode, NotificationItem, Posting } from "@/types";

function node(
  id: string,
  title: string,
  subtitle: string,
  domain: string,
  kind: string,
  rank: number,
  progressStatus: string | null = null,
): CareerNode {
  return {
    id: `demo-${id}`,
    canonicalKey: `demo.${id}`,
    title,
    subtitle,
    domain,
    kind,
    scopeDefinition: `${subtitle}를 실제 결과물로 완성하고 성장 기록에 남기는 단계입니다.`,
    level: Math.min(rank + 1, 5),
    detail: {
      selfConfirmable: true,
      estimatedDuration: rank < 2 ? "3일" : "1~2주",
      outcomes: ["완료 결과물 1개", "회고 및 학습 기록", "포트폴리오 증빙"],
      quests: [
        {
          title: `${title} 핵심 과제`,
          description: `${subtitle}에 필요한 핵심 내용을 직접 수행합니다.`,
          doneCriteria: "결과물과 배운 점을 한 문단으로 정리합니다.",
        },
      ],
    },
    rank,
    progressStatus,
    completionMethod: progressStatus === "COMPLETED" ? "SELF_CONFIRMED" : null,
    completedAt: progressStatus === "COMPLETED" ? new Date().toISOString() : null,
  };
}

const nodes = [
  node("goal", "목표 공고 설정", "금융 IT 백엔드 개발자", "COMMON", "FOUNDATION", 0, "COMPLETED"),
  node("diagnosis", "AI 역량 진단", "이력서와 공고 비교 분석", "COMMON", "SKILL", 1, "COMPLETED"),
  node("git", "Git 협업 루틴", "브랜치·PR·코드 리뷰", "COMMON", "SKILL", 2, "IN_PROGRESS"),
  node("portfolio", "포트폴리오 설계", "성과 중심 프로젝트 스토리", "COMMON", "EXPERIENCE", 3),
  node("java", "Java 핵심 문법", "객체지향과 컬렉션", "BACKEND", "SKILL", 1, "COMPLETED"),
  node("spring", "Spring Boot API", "REST API와 예외 처리", "BACKEND", "PROJECT", 2, "IN_PROGRESS"),
  node("database", "SQL·데이터 모델링", "금융 데이터 쿼리 20제", "BACKEND", "SKILL", 3),
  node("security", "인증·보안", "JWT와 Spring Security", "BACKEND", "CREDENTIAL", 4),
  node("vue", "Vue 컴포넌트", "반응형 UI와 상태 관리", "FRONTEND", "SKILL", 1, "COMPLETED"),
  node("design", "UI 시스템 구축", "J.O.B.I.S 디자인 토큰", "FRONTEND", "PROJECT", 2, "IN_PROGRESS"),
  node("accessibility", "접근성·반응형", "키보드와 모바일 최적화", "FRONTEND", "CREDENTIAL", 3),
  node("deploy", "클라우드 배포", "Docker와 CI/CD", "CLOUD", "PROJECT", 2),
  node("monitoring", "모니터링", "로그·메트릭·알림", "CLOUD", "SKILL", 3),
  node("interview", "AI 모의 면접", "기술·인성 질문 12개", "COMMON", "OPPORTUNITY_CLUSTER", 4),
  node("apply", "최종 지원", "서류 점검과 지원 완료", "COMMON", "OPPORTUNITY", 5),
];

const edgePairs = [
  ["goal", "diagnosis"],
  ["diagnosis", "git"],
  ["diagnosis", "java"],
  ["diagnosis", "vue"],
  ["java", "spring"],
  ["vue", "design"],
  ["spring", "database"],
  ["design", "accessibility"],
  ["spring", "deploy"],
  ["deploy", "monitoring"],
  ["git", "portfolio"],
  ["database", "security"],
  ["portfolio", "interview"],
  ["security", "interview"],
  ["accessibility", "interview"],
  ["monitoring", "interview"],
  ["interview", "apply"],
];

export const showcaseCareerMap: CareerMap = {
  graph: {
    id: "demo-career-map",
    title: "금융 IT 개발자 합격 로드맵",
    version: 1,
    updatedAt: new Date().toISOString(),
  },
  nodes,
  edges: edgePairs.map(([from, to], index) => ({
    id: `demo-edge-${index}`,
    fromNodeId: `demo-${from}`,
    toNodeId: `demo-${to}`,
    edgeKind: "PREREQUISITE",
  })),
  requirements: [],
};

export const showcasePostings: Posting[] = [
  {
    id: "demo-posting-bank",
    sourceType: "TEXT",
    sourceUrl: null,
    companyName: "광주은행",
    roleTitle: "디지털·IT 개발",
    experienceText: "신입",
    analysisJobId: null,
    analysisStatus: "SUCCEEDED",
    archivedAt: null,
    createdAt: new Date().toISOString(),
  },
  {
    id: "demo-posting-fintech",
    sourceType: "TEXT",
    sourceUrl: null,
    companyName: "핀테크 스타트업",
    roleTitle: "백엔드 엔지니어",
    experienceText: "신입·경력",
    analysisJobId: null,
    analysisStatus: "SUCCEEDED",
    archivedAt: null,
    createdAt: new Date().toISOString(),
  },
];

function minutesAgo(minutes: number) {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

export const showcaseNotifications: NotificationItem[] = [
  {
    id: "demo-activity-1",
    type: "ROADMAP_PROGRESS",
    title: "Vue 컴포넌트 단계를 완료했어요",
    body: "반응형 화면과 공통 컴포넌트를 성장 증거로 기록했습니다.",
    payload: {},
    readAt: null,
    createdAt: minutesAgo(18),
  },
  {
    id: "demo-activity-2",
    type: "ANALYSIS_COMPLETED",
    title: "광주은행 공고 분석이 끝났어요",
    body: "필수 역량 6개와 우대 역량 3개를 커리어 지도에 연결했습니다.",
    payload: {},
    readAt: minutesAgo(44),
    createdAt: minutesAgo(46),
  },
  {
    id: "demo-activity-3",
    type: "CAREER_MAP_UPDATED",
    title: "새로운 행성 3개가 열렸어요",
    body: "Spring Boot API, 데이터 모델링, 클라우드 배포 경로가 추가됐습니다.",
    payload: {},
    readAt: minutesAgo(120),
    createdAt: minutesAgo(125),
  },
  {
    id: "demo-activity-4",
    type: "EVIDENCE_VERIFIED",
    title: "프로젝트 증빙을 확인했어요",
    body: "J.O.B.I.S 프론트엔드 작업이 포트폴리오 증빙으로 승인됐습니다.",
    payload: {},
    readAt: minutesAgo(380),
    createdAt: minutesAgo(385),
  },
  {
    id: "demo-activity-5",
    type: "QUEST_RECOMMENDED",
    title: "오늘의 추천 퀘스트가 도착했어요",
    body: "Spring Boot 예외 처리 과제를 완료하면 35 XP를 받을 수 있어요.",
    payload: {},
    readAt: minutesAgo(900),
    createdAt: minutesAgo(905),
  },
];
