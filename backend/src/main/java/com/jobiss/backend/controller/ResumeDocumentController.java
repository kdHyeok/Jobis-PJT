package com.jobiss.backend.controller;

import com.jobiss.backend.dto.resume.ResumeDocumentDtos.Detail;
import com.jobiss.backend.dto.resume.ResumeDocumentDtos.SaveRequest;
import com.jobiss.backend.dto.resume.ResumeDocumentDtos.Summary;
import com.jobiss.backend.service.ResumeDocumentService;
import jakarta.validation.Valid;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/** 이력서 원문 보관 — 저장·목록·불러오기·삭제. */
@RestController
@RequestMapping("/api/resumes")
public class ResumeDocumentController {

    private final ResumeDocumentService service;

    public ResumeDocumentController(ResumeDocumentService service) {
        this.service = service;
    }

    /** 내 이력서 목록(본문 제외, 미리보기만). */
    @GetMapping
    public List<Summary> list(@AuthenticationPrincipal Long userId) {
        return service.list(userId);
    }

    /** 단건 — 원문 포함(불러오기용). */
    @GetMapping("/{id}")
    public Detail get(@AuthenticationPrincipal Long userId, @PathVariable Long id) {
        return service.get(userId, id);
    }

    /** 저장 또는 갱신(id 있으면 갱신). */
    @PostMapping
    public Detail save(@AuthenticationPrincipal Long userId, @Valid @RequestBody SaveRequest request) {
        return service.save(userId, request);
    }

    @DeleteMapping("/{id}")
    public Map<String, Object> delete(@AuthenticationPrincipal Long userId, @PathVariable Long id) {
        service.delete(userId, id);
        return Map.of("deleted", true);
    }
}
