package com.jobiss.backend.controller;

import com.jobiss.backend.dto.roadmap.GenerateRoadmapRequest;
import com.jobiss.backend.dto.roadmap.SavedRoadmapResponse;
import com.jobiss.backend.service.SavedRoadmapService;
import jakarta.validation.Valid;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** 로드맵 생성/저장. (저장소 목록·대표 지정은 다음 arc에서 GET/PATCH 추가) */
@RestController
@RequestMapping("/api/roadmaps")
public class RoadmapController {

    private final SavedRoadmapService savedRoadmapService;

    public RoadmapController(SavedRoadmapService savedRoadmapService) {
        this.savedRoadmapService = savedRoadmapService;
    }

    /** 이 경로로 로드맵 생성(=AI가 맥락 반영해 정리) 후 저장. */
    @PostMapping
    public SavedRoadmapResponse generate(@AuthenticationPrincipal Long userId,
                                         @Valid @RequestBody GenerateRoadmapRequest request) {
        return savedRoadmapService.generate(userId, request);
    }

    /** 로드맵 저장소 목록(내 것, 최신순). */
    @GetMapping
    public List<SavedRoadmapResponse> list(@AuthenticationPrincipal Long userId) {
        return savedRoadmapService.list(userId);
    }

    /** 대표 로드맵 지정(한 사용자에 하나). */
    @PostMapping("/{id}/representative")
    public SavedRoadmapResponse setRepresentative(@AuthenticationPrincipal Long userId, @PathVariable Long id) {
        return savedRoadmapService.setRepresentative(userId, id);
    }
}
