// 업로드된 이력서 파일 → `createCareerSource` 페이로드 조각.
//
// **두 화면(커리어 저장소·대화)이 같은 규칙을 봐야 한다.** 각자 파일을 읽으면 한쪽만
// docx 를 지원하는 상태가 조용히 생긴다 — 실제로 저장소 화면은 `file.text()` 로만 읽어서
// docx 를 올리면 깨진 바이트가 원문으로 등록됐다.
//
// docx 는 ZIP 컨테이너라 브라우저에서 텍스트로 읽을 수 없다. 바이트를 base64 로 올리고
// 서버(`DocumentText`)가 표준 라이브러리 zip 으로 푼다 — 프론트에 파싱 라이브러리를
// 들이지 않는 쪽을 골랐다.

export const RESUME_ACCEPT = ".docx,.txt,.md";
export const RESUME_MAX_BYTES = 2_000_000;
// 서버 `CreateSourceRequest.rawText` 의 최소 길이와 같은 값 — 여기서만 통과시키면
// 등록 버튼을 눌렀을 때 400 이 난다.
export const RESUME_MIN_CHARS = 20;

export type ResumeFilePayload = {
  rawText: string;
  fileBase64?: string;
  fileName: string;
};

/** 파일 하나를 읽어 등록 페이로드로. 크기·형식 위반은 사용자에게 보일 문장으로 던진다. */
export async function readResumeFile(file: File): Promise<ResumeFilePayload> {
  if (file.size > RESUME_MAX_BYTES) {
    throw new Error("파일은 2MB 이하만 등록할 수 있습니다.");
  }
  if (file.name.toLowerCase().endsWith(".docx")) {
    // 원문은 서버가 채운다 — 여기서 빈 문자열로 두는 것이 계약이다.
    return { rawText: "", fileBase64: await toBase64(file), fileName: file.name };
  }
  return { rawText: await file.text(), fileName: file.name };
}

/** 파일명에서 확장자를 떼어 기본 제목으로. */
export function titleFromFileName(fileName: string): string {
  return fileName.replace(/\.[^.]+$/, "");
}

async function toBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  // 인자 스프레드에는 개수 상한이 있다 — 2MB 를 한 번에 넘기면 RangeError 로 죽는다.
  const CHUNK = 0x8000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + CHUNK));
  }
  return btoa(binary);
}
