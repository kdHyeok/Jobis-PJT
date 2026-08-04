package com.jobiss.career.repository;

import com.jobiss.common.ApiException;
import org.springframework.http.HttpStatus;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * 업로드된 이력서 파일 → 텍스트.
 *
 * <p>왜 서버에서 푸는가: 브라우저는 {@code file.text()} 로 md·txt 는 읽지만 <b>docx 는 ZIP
 * 컨테이너</b>라 바이트를 문자로 읽으면 깨진다. 그래서 프론트는 파일을 base64 로 올리고
 * 여기서 텍스트를 뽑아 기존 {@code career_sources.raw_text} 계약에 그대로 넣는다 —
 * DB 스키마도, AI 계약도 바뀌지 않는다.
 *
 * <p>왜 새 라이브러리를 안 쓰는가: docx 는 ZIP 안의 {@code word/document.xml} 이고, 필요한
 * 것은 그 XML 의 글자뿐이다. {@code java.util.zip} 이 표준 라이브러리에 있으므로 Apache POI
 * (수 MB·전이 의존성 다수)를 들일 이유가 없다. 서식·표·이미지는 버린다 — 이력서 판정에
 * 쓰이는 것은 문장이고, 하류(AI)도 텍스트만 읽는다.
 */
final class DocumentText {

    /** docx 본문이 들어 있는 항목. 머리말·꼬리말·주석은 이력서 본문이 아니라 읽지 않는다. */
    private static final String DOCX_BODY = "word/document.xml";

    private DocumentText() {
    }

    /**
     * 업로드 파일의 텍스트. 형식은 파일명 확장자로 가른다(브라우저 MIME 은 OS 설정에 따라
     * 비거나 틀리게 온다 — 실제로 docx 가 {@code application/octet-stream} 으로 온다).
     *
     * @throws ApiException base64 가 깨졌거나 지원하지 않는 형식일 때 (400)
     */
    static String fromUpload(String fileName, String base64) {
        byte[] bytes;
        try {
            bytes = Base64.getDecoder().decode(base64 == null ? "" : base64.strip());
        } catch (IllegalArgumentException cause) {
            throw badFile("파일을 읽지 못했습니다. 다시 올려 주세요.", cause);
        }
        String name = fileName == null ? "" : fileName.toLowerCase();
        if (name.endsWith(".docx")) {
            return docxText(bytes);
        }
        if (name.endsWith(".md") || name.endsWith(".txt") || name.endsWith(".csv")
                || name.endsWith(".json")) {
            return new String(bytes, StandardCharsets.UTF_8);
        }
        throw badFile("지원하지 않는 파일 형식입니다: md, txt, docx 로 올려 주세요.", null);
    }

    /** 파일 탓의 실패는 서버 오류가 아니라 400 이다 — 사용자가 고칠 수 있는 문장을 그대로 낸다. */
    private static ApiException badFile(String message, Throwable cause) {
        ApiException failure = new ApiException(HttpStatus.BAD_REQUEST, "INVALID_FILE", message);
        if (cause != null) {
            // 원인을 붙여 둔다 — 400 으로 나가면 스택이 로그에 안 남아, 깨진 파일이
            // 어떻게 깨졌는지 나중에 알 방법이 사라진다.
            failure.initCause(cause);
        }
        return failure;
    }

    private static String docxText(byte[] bytes) {
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(bytes))) {
            for (ZipEntry entry = zip.getNextEntry(); entry != null; entry = zip.getNextEntry()) {
                if (DOCX_BODY.equals(entry.getName())) {
                    return stripMarkup(new String(zip.readAllBytes(), StandardCharsets.UTF_8));
                }
            }
        } catch (IOException cause) {
            throw badFile("docx 파일을 열지 못했습니다. 다시 저장해 올려 주세요.", cause);
        }
        throw badFile("docx 본문을 찾지 못했습니다. 다시 저장해 올려 주세요.", null);
    }

    /**
     * WordprocessingML → 평문. 단락·줄바꿈·탭을 <b>먼저</b> 공백 문자로 바꾼 뒤 태그를 지운다 —
     * 순서를 뒤집으면 모든 단락이 한 줄로 붙어 하류 파서가 항목 경계를 잃는다.
     */
    private static String stripMarkup(String xml) {
        String text = xml
                .replaceAll("(?i)<w:tab\\b[^>]*/?>", "\t")
                .replaceAll("(?i)<w:br\\b[^>]*/?>", "\n")
                .replaceAll("(?i)</w:p>", "\n")
                .replaceAll("<[^>]+>", "");
        // XML 엔티티 복원 — &amp; 를 마지막에 풀어야 "&amp;lt;" 가 "<" 로 두 번 풀리지 않는다.
        text = text.replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", "\"").replace("&apos;", "'")
                .replace("&amp;", "&");
        // 빈 단락이 줄줄이 남는다(docx 는 서식용 빈 <w:p> 를 많이 쓴다) — 셋 이상은 둘로 줄인다.
        return text.replaceAll("[ \t]+\n", "\n").replaceAll("\n{3,}", "\n\n").strip();
    }
}
