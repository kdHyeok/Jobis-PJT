export type RoadmapNodeState = "complete" | "current" | "available" | "locked";

export type RoadmapNode = {
  id: string;
  title: string;
  subtitle: string;
  duration: string;
  state: RoadmapNodeState;
  category: "analysis" | "skill" | "project" | "document" | "interview" | "goal";
  xp: number;
  description: string;
  checklist: string[];
  unlockHint?: string;
};

export type TodayTask = {
  id: number;
  title: string;
  meta: string;
  minutes: number;
  xp: number;
  done: boolean;
};

export const initialRoadmapNodes: RoadmapNode[] = [
  {
    id: "goal",
    title: "목표 공고 설정",
    subtitle: "광주은행 디지털·IT",
    duration: "완료",
    state: "complete",
    category: "goal",
    xp: 20,
    description: "지원하려는 공고와 마감일을 기준으로 준비 경로를 만들었습니다.",
    checklist: ["공고 URL 등록", "채용 요건 분석", "마감일 확인"],
  },
  {
    id: "gap",
    title: "역량 진단",
    subtitle: "보유 경험과 공고 비교",
    duration: "완료",
    state: "complete",
    category: "analysis",
    xp: 35,
    description: "프로젝트와 활동 증거를 공고의 필수·우대 요건과 비교했습니다.",
    checklist: ["경험 6개 등록", "핵심 역량 8개 추출", "부족한 역량 확인"],
  },
  {
    id: "sql",
    title: "SQL 실전 역량",
    subtitle: "금융 데이터 쿼리 20제",
    duration: "6일 남음",
    state: "current",
    category: "skill",
    xp: 80,
    description: "금융 데이터를 직접 조회하고 집계하는 실전 SQL 역량을 보완합니다.",
    checklist: ["JOIN 문제 5개", "윈도 함수 문제 5개", "쿼리 리뷰 기록"],
  },
  {
    id: "project",
    title: "금융 API 미니 프로젝트",
    subtitle: "경험 증거를 결과물로",
    duration: "예상 10일",
    state: "available",
    category: "project",
    xp: 120,
    description: "공고에서 요구하는 API 설계와 데이터 처리 역량을 한 번에 증명합니다.",
    checklist: ["API 명세 작성", "핵심 기능 구현", "README와 회고 정리"],
  },
  {
    id: "portfolio",
    title: "포트폴리오 정리",
    subtitle: "프로젝트 2개를 공고 언어로",
    duration: "예상 4일",
    state: "locked",
    category: "document",
    xp: 70,
    description: "기술 나열 대신 문제·행동·결과가 보이는 포트폴리오로 재구성합니다.",
    checklist: ["핵심 성과 수치화", "공고 키워드 반영", "한 페이지 요약"],
    unlockHint: "금융 API 미니 프로젝트를 완료하면 열립니다.",
  },
  {
    id: "essay",
    title: "자기소개서 완성",
    subtitle: "경험 근거 중심 3문항",
    duration: "예상 3일",
    state: "locked",
    category: "document",
    xp: 90,
    description: "공고 요구 역량과 실제 경험이 자연스럽게 연결되도록 문항을 완성합니다.",
    checklist: ["STAR 구조 초안", "근거 연결 검토", "최종 문장 다듬기"],
    unlockHint: "포트폴리오 정리를 완료하면 열립니다.",
  },
  {
    id: "interview",
    title: "모의 면접",
    subtitle: "기술·인성 질문 12개",
    duration: "예상 2일",
    state: "locked",
    category: "interview",
    xp: 100,
    description: "지원 직무에 맞춘 예상 질문으로 답변의 근거와 전달력을 점검합니다.",
    checklist: ["기술 질문 6개", "경험 질문 4개", "지원동기·마무리"],
    unlockHint: "자기소개서를 완료하면 열립니다.",
  },
  {
    id: "apply",
    title: "지원 완료",
    subtitle: "마감 전 최종 점검",
    duration: "D-42",
    state: "locked",
    category: "goal",
    xp: 200,
    description: "모든 제출물과 지원 정보를 확인하고 목표 공고에 지원합니다.",
    checklist: ["첨부파일 점검", "지원서 오탈자 확인", "최종 제출"],
    unlockHint: "모의 면접까지 완료하면 도착합니다.",
  },
];

export const initialTodayTasks: TodayTask[] = [
  {
    id: 1,
    title: "JOIN 실전 문제 3개 풀기",
    meta: "SQL 실전 역량 · 핵심 과제",
    minutes: 35,
    xp: 12,
    done: true,
  },
  {
    id: 2,
    title: "쿼리 실행 계획 비교하기",
    meta: "SQL 실전 역량 · 심화",
    minutes: 25,
    xp: 10,
    done: false,
  },
  {
    id: 3,
    title: "프로젝트 README 성과 한 줄 쓰기",
    meta: "포트폴리오 준비 · 가벼운 과제",
    minutes: 15,
    xp: 8,
    done: false,
  },
];
