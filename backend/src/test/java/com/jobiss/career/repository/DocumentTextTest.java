package com.jobiss.career.repository;

import com.jobiss.common.ApiException;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class DocumentTextTest {

    @Test
    void readsUtf8Text() {
        String text = "백엔드 개발자 이력서입니다. Java와 Spring 프로젝트를 진행했습니다.";

        assertThat(DocumentText.fromUpload(
                "resume.txt",
                text.getBytes(StandardCharsets.UTF_8)
        )).isEqualTo(text);
    }

    @Test
    void readsParagraphsFromDocxWithoutLoadingOtherZipEntries() throws Exception {
        String document = """
                <?xml version="1.0" encoding="UTF-8"?>
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>Java Spring 프로젝트 경험</w:t></w:r></w:p>
                    <w:p><w:r><w:t>응답 시간을 30% 개선했습니다.</w:t></w:r></w:p>
                  </w:body>
                </w:document>
                """;
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(bytes)) {
            zip.putNextEntry(new ZipEntry("word/document.xml"));
            zip.write(document.getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
        }

        String extracted = DocumentText.fromUpload("resume.docx", bytes.toByteArray());

        assertThat(extracted).contains("Java Spring 프로젝트 경험");
        assertThat(extracted).contains("응답 시간을 30% 개선했습니다.");
    }

    @Test
    void rejectsUnsupportedFiles() {
        assertThatThrownBy(() -> DocumentText.fromUpload(
                "resume.exe",
                "not an allowed document format".getBytes(StandardCharsets.UTF_8)
        ))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("DOCX, TXT, MD");
    }
}
