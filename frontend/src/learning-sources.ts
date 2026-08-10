import type { LearningResource } from "@/learning-plan";

type CuratedSource = Omit<LearningResource, "id" | "enabled"> & { keywords: string[] };

// Curated from feat/learning-plan:data-pipeline/data/learning-sources.csv.
// Link-safe references are exposed here; ingest-only content remains in the pipeline.
const SOURCES: CuratedSource[] = [
  { title: "WeareSoft 기술 면접 자료", url: "https://github.com/WeareSoft/tech-interview", kind: "COMMUNITY", keywords: ["cs", "computer", "운영체제", "자료구조", "네트워크"] },
  { title: "생활코딩", url: "https://opentutorials.org/", kind: "COMMUNITY", keywords: ["program", "foundation", "프로그래밍", "기초"] },
  { title: "gyoogle 기술면접 백과", url: "https://github.com/gyoogle/tech-interview-for-developer", kind: "COMMUNITY", keywords: ["cs", "자료구조", "알고리즘", "운영체제", "네트워크", "database"] },
  { title: "MDN HTTP", url: "https://developer.mozilla.org/ko/docs/Web/HTTP", kind: "OFFICIAL", keywords: ["http", "web", "network", "네트워크"] },
  { title: "PostgreSQL 공식 문서", url: "https://www.postgresql.org/docs/current/", kind: "OFFICIAL", keywords: ["postgres", "sql", "database", "데이터베이스"] },
  { title: "Python 공식 튜토리얼", url: "https://docs.python.org/ko/3/tutorial/", kind: "OFFICIAL", keywords: ["python", "파이썬"] },
  { title: "Dev.java 공식 학습 경로", url: "https://dev.java/learn/", kind: "OFFICIAL", keywords: ["java", "자바"] },
];

export function curatedLearningResources(canonicalKey: string, title: string): LearningResource[] {
  const haystack = `${canonicalKey} ${title}`.toLowerCase();
  return SOURCES
    .filter((source) => source.keywords.some((keyword) => haystack.includes(keyword)))
    .slice(0, 4)
    .map((source) => ({ ...source, id: crypto.randomUUID(), enabled: true }));
}
