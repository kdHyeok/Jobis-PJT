package com.jobiss.backend.dto.resume;

import com.jobiss.backend.domain.ResumeDocument;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.time.LocalDateTime;

/** 이력서 원문 보관 관련 DTO 모음. */
public final class ResumeDocumentDtos {

    private ResumeDocumentDtos() {
    }

    /** 저장/수정 요청. id가 있으면 그 문서를 갱신한다. */
    public record SaveRequest(
            Long id,
            @Size(max = 150) String title,
            @NotBlank @Size(max = 60000) String content,
            @Size(max = 20) String sourceType
    ) {
    }

    /** 목록용(원문 본문 제외 — 목록에서 수만 KB를 실어 나르지 않는다). */
    public record Summary(
            Long id, String title, String sourceType, int length,
            String preview, LocalDateTime updatedAt
    ) {
        public static Summary of(ResumeDocument d) {
            String c = d.getContent() == null ? "" : d.getContent();
            String preview = c.length() > 120 ? c.substring(0, 120) + "…" : c;
            return new Summary(d.getId(), d.getTitle(), d.getSourceType(), c.length(),
                    preview.replaceAll("\\s+", " ").trim(), d.getUpdatedAt());
        }
    }

    /** 단건 조회용(원문 포함 — "불러오기"에서 사용). */
    public record Detail(
            Long id, String title, String sourceType, String content, LocalDateTime updatedAt
    ) {
        public static Detail of(ResumeDocument d) {
            return new Detail(d.getId(), d.getTitle(), d.getSourceType(), d.getContent(), d.getUpdatedAt());
        }
    }
}
