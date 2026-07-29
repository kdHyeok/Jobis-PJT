package com.jobiss.backend.service;

import com.jobiss.backend.domain.ResumeDocument;
import com.jobiss.backend.dto.resume.ResumeDocumentDtos.Detail;
import com.jobiss.backend.dto.resume.ResumeDocumentDtos.SaveRequest;
import com.jobiss.backend.dto.resume.ResumeDocumentDtos.Summary;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.repository.ResumeDocumentRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 이력서 원문 보관. 파편화하면 조각만 남던 것을, 원문까지 남겨 다시 불러 쓸 수 있게 한다.
 * 조각(Evidence)과의 연결은 evidences.resume_document_id (느슨한 참조 — 원문을 지워도 조각은 남는다).
 */
@Service
public class ResumeDocumentService {

    private static final int MAX_PER_USER = 20;   // 무한 누적 방지

    private final ResumeDocumentRepository repository;

    public ResumeDocumentService(ResumeDocumentRepository repository) {
        this.repository = repository;
    }

    @Transactional(readOnly = true)
    public List<Summary> list(Long userId) {
        return repository.findByUserIdOrderByUpdatedAtDesc(userId).stream().map(Summary::of).toList();
    }

    @Transactional(readOnly = true)
    public Detail get(Long userId, Long id) {
        return Detail.of(requireOwned(userId, id));
    }

    /** 저장 또는 갱신. id가 있으면 그 문서를 고치고, 없으면 새로 만든다. */
    @Transactional
    public Detail save(Long userId, SaveRequest req) {
        if (req.id() != null) {
            ResumeDocument doc = requireOwned(userId, req.id());
            doc.update(req.title(), req.content());
            return Detail.of(doc);   // dirty checking
        }
        if (repository.countByUserId(userId) >= MAX_PER_USER) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "TOO_MANY_RESUMES",
                    "보관할 수 있는 이력서는 최대 " + MAX_PER_USER + "개예요. 오래된 것을 지우고 다시 시도해 주세요.");
        }
        ResumeDocument saved = repository.save(ResumeDocument.builder()
                .userId(userId)
                .title(defaultTitle(req.title(), req.content()))
                .sourceType(req.sourceType() == null || req.sourceType().isBlank() ? "TEXT" : req.sourceType())
                .content(req.content())
                .build());
        return Detail.of(saved);
    }

    @Transactional
    public void delete(Long userId, Long id) {
        repository.delete(requireOwned(userId, id));
        // 조각의 resume_document_id 는 그대로 둔다 — 조각 자체는 증거로 계속 쓰인다.
    }

    private ResumeDocument requireOwned(Long userId, Long id) {
        ResumeDocument doc = repository.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RESUME_NOT_FOUND", "이력서를 찾을 수 없습니다."));
        if (!doc.getUserId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "접근 권한이 없습니다.");
        }
        return doc;
    }

    /** 제목이 없으면 본문 첫 줄에서 만든다. */
    private static String defaultTitle(String title, String content) {
        if (title != null && !title.isBlank()) return cap(title.trim(), 150);
        String first = content == null ? "" : content.strip().lines().findFirst().orElse("").strip();
        first = first.replaceFirst("^제목\\s*[:：]\\s*", "");
        return first.isBlank() ? "이력서" : cap(first, 150);
    }

    private static String cap(String s, int n) {
        return s.length() > n ? s.substring(0, n) : s;
    }
}
