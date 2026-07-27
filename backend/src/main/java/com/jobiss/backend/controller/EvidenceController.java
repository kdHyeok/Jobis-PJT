package com.jobiss.backend.controller;

import com.jobiss.backend.dto.evidence.BulkImportRequest;
import com.jobiss.backend.dto.evidence.BulkImportResponse;
import com.jobiss.backend.dto.evidence.EvidenceCreateRequest;
import com.jobiss.backend.dto.evidence.EvidenceResponse;
import com.jobiss.backend.dto.evidence.ImportParseRequest;
import com.jobiss.backend.dto.evidence.ImportParseResponse;
import com.jobiss.backend.service.EvidenceImportService;
import com.jobiss.backend.service.EvidenceService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/evidences")
public class EvidenceController {

    private final EvidenceService evidenceService;
    private final EvidenceImportService importService;

    public EvidenceController(EvidenceService evidenceService, EvidenceImportService importService) {
        this.evidenceService = evidenceService;
        this.importService = importService;
    }

    @GetMapping
    public List<EvidenceResponse> list(@AuthenticationPrincipal Long userId) {
        return evidenceService.list(userId);
    }

    @PostMapping
    public ResponseEntity<EvidenceResponse> create(@AuthenticationPrincipal Long userId,
                                                   @Valid @RequestBody EvidenceCreateRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(evidenceService.create(userId, request));
    }

    /** 자료 업로드 → (가짜)AI 파싱. 조각 후보만 반환(저장 안 함). */
    @PostMapping("/parse")
    public ImportParseResponse parse(@AuthenticationPrincipal Long userId,
                                     @Valid @RequestBody ImportParseRequest request) {
        return importService.parse(userId, request);
    }

    /** 사용자가 확인·선택한 조각들을 저장소에 등록(STACK 중복 제거). */
    @PostMapping("/import")
    public BulkImportResponse importSelected(@AuthenticationPrincipal Long userId,
                                             @Valid @RequestBody BulkImportRequest request) {
        return importService.importSelected(userId, request);
    }
}
