package com.jobiss.career.repository;

import com.jobiss.common.ApiException;
import org.springframework.http.HttpStatus;

import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamConstants;
import javax.xml.stream.XMLStreamException;
import javax.xml.stream.XMLStreamReader;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

final class DocumentText {

    static final int MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
    private static final int MAX_DOCUMENT_XML_BYTES = 12 * 1024 * 1024;
    private static final int MAX_TEXT_CHARS = 100_000;

    private DocumentText() {
    }

    static String fromUpload(String fileName, byte[] bytes) {
        if (bytes == null || bytes.length == 0) {
            throw badRequest("EMPTY_DOCUMENT", "내용이 있는 파일을 선택해 주세요.");
        }
        if (bytes.length > MAX_UPLOAD_BYTES) {
            throw badRequest("DOCUMENT_TOO_LARGE", "파일은 5MB 이하만 등록할 수 있습니다.");
        }
        String safeName = fileName == null ? "" : fileName.strip();
        String lowered = safeName.toLowerCase(Locale.ROOT);
        String text;
        if (lowered.endsWith(".docx")) {
            text = fromDocx(bytes);
        } else if (lowered.endsWith(".txt") || lowered.endsWith(".md")) {
            text = new String(bytes, StandardCharsets.UTF_8)
                    .replace("\uFEFF", "")
                    .replace("\u0000", "");
        } else {
            throw badRequest(
                    "UNSUPPORTED_DOCUMENT_TYPE",
                    "DOCX, TXT, MD 파일만 등록할 수 있습니다."
            );
        }
        text = normalize(text);
        if (text.length() < 20) {
            throw badRequest(
                    "DOCUMENT_TEXT_TOO_SHORT",
                    "파일에서 분석할 수 있는 글을 충분히 찾지 못했습니다."
            );
        }
        return text.length() > MAX_TEXT_CHARS
                ? text.substring(0, MAX_TEXT_CHARS)
                : text;
    }

    private static String fromDocx(byte[] bytes) {
        byte[] documentXml = null;
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(bytes))) {
            ZipEntry entry;
            int entries = 0;
            while ((entry = zip.getNextEntry()) != null) {
                entries += 1;
                if (entries > 2_000) {
                    throw badRequest("INVALID_DOCUMENT", "DOCX 내부 항목이 너무 많습니다.");
                }
                if (entry.isDirectory() || !"word/document.xml".equals(entry.getName())) {
                    continue;
                }
                documentXml = readBounded(zip, MAX_DOCUMENT_XML_BYTES);
                break;
            }
        } catch (IOException exception) {
            throw badRequest("INVALID_DOCUMENT", "DOCX 파일을 읽지 못했습니다.");
        }
        if (documentXml == null) {
            throw badRequest("INVALID_DOCUMENT", "올바른 DOCX 문서가 아닙니다.");
        }
        return readWordXml(documentXml);
    }

    private static byte[] readBounded(ZipInputStream input, int limit) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8_192];
        int total = 0;
        int read;
        while ((read = input.read(buffer)) >= 0) {
            total += read;
            if (total > limit) {
                throw badRequest(
                        "DOCUMENT_TOO_LARGE",
                        "압축을 푼 문서 내용이 허용 크기를 초과했습니다."
                );
            }
            output.write(buffer, 0, read);
        }
        return output.toByteArray();
    }

    private static String readWordXml(byte[] xml) {
        XMLInputFactory factory = XMLInputFactory.newFactory();
        factory.setProperty(XMLInputFactory.SUPPORT_DTD, false);
        factory.setProperty("javax.xml.stream.isSupportingExternalEntities", false);
        StringBuilder text = new StringBuilder();
        try {
            XMLStreamReader reader = factory.createXMLStreamReader(
                    new ByteArrayInputStream(xml),
                    StandardCharsets.UTF_8.name()
            );
            while (reader.hasNext() && text.length() <= MAX_TEXT_CHARS) {
                int event = reader.next();
                if (event == XMLStreamConstants.START_ELEMENT) {
                    String name = reader.getLocalName();
                    if ("t".equals(name)) {
                        text.append(reader.getElementText());
                    } else if ("tab".equals(name)) {
                        text.append('\t');
                    } else if ("br".equals(name)) {
                        text.append('\n');
                    }
                } else if (event == XMLStreamConstants.END_ELEMENT
                        && "p".equals(reader.getLocalName())) {
                    text.append('\n');
                }
            }
            reader.close();
        } catch (XMLStreamException exception) {
            throw badRequest("INVALID_DOCUMENT", "DOCX 본문 형식을 읽지 못했습니다.");
        }
        return text.toString();
    }

    private static String normalize(String text) {
        return text.replace("\r\n", "\n")
                .replace('\r', '\n')
                .replaceAll("[\\t ]+", " ")
                .replaceAll("\\n{3,}", "\n\n")
                .strip();
    }

    private static ApiException badRequest(String code, String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, code, message);
    }
}
