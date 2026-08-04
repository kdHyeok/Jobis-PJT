package com.jobiss.career.repository;

import com.jobiss.common.ApiException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * docx 텍스트 추출 — 표준 라이브러리 zip 으로 푼다는 결정(새 의존성 없음)의 검증.
 *
 * <p>docx 를 테스트 자원 파일로 두지 않고 여기서 만든다: 바이너리 픽스처는 무엇이 들어 있는지
 * 리뷰에서 보이지 않고, 필요한 것은 "ZIP 안의 word/document.xml" 이라는 구조뿐이다.
 */
class DocumentTextTest {

    private static String docxBase64(String bodyXml) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(bytes)) {
            zip.putNextEntry(new ZipEntry("[Content_Types].xml"));
            zip.write("<Types/>".getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
            zip.putNextEntry(new ZipEntry("word/document.xml"));
            zip.write(bodyXml.getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
        }
        return Base64.getEncoder().encodeToString(bytes.toByteArray());
    }

    @Test
    @DisplayName("docx 의 단락이 줄바꿈으로 남는다 — 한 줄로 붙으면 하류가 항목 경계를 잃는다")
    void extractsParagraphsFromDocx() throws Exception {
        String body = """
                <w:document><w:body>
                <w:p><w:r><w:t>백엔드 개발자 김지원</w:t></w:r></w:p>
                <w:p><w:r><w:t>Java</w:t></w:r><w:r><w:t> &amp; Kotlin</w:t></w:r></w:p>
                <w:p/>
                <w:p><w:r><w:t>Spring Boot 3</w:t></w:r></w:p>
                </w:body></w:document>
                """;

        String text = DocumentText.fromUpload("이력서.docx", docxBase64(body));

        assertThat(text.lines()).containsSubsequence(
                "백엔드 개발자 김지원", "Java & Kotlin", "Spring Boot 3");
    }

    @Test
    @DisplayName("md 는 바이트를 그대로 UTF-8 로 읽는다")
    void readsMarkdownAsText() {
        String md = "# 이력서\n- Python 3년";
        String base64 = Base64.getEncoder().encodeToString(md.getBytes(StandardCharsets.UTF_8));

        assertThat(DocumentText.fromUpload("resume.md", base64)).isEqualTo(md);
    }

    @Test
    @DisplayName("지원하지 않는 형식·깨진 파일은 400 — 서버 오류가 아니다")
    void rejectsUnsupportedAndBrokenFiles() {
        String ok = Base64.getEncoder().encodeToString("내용".getBytes(StandardCharsets.UTF_8));

        assertThatThrownBy(() -> DocumentText.fromUpload("resume.pages", ok))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("지원하지 않는 파일 형식");
        // docx 라 주장하지만 ZIP 이 아니다 — 사용자가 확장자만 바꿨을 때.
        assertThatThrownBy(() -> DocumentText.fromUpload("resume.docx", ok))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("docx");
    }
}
