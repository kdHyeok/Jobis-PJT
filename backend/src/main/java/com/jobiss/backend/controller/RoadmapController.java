package com.jobiss.backend.controller;

import com.jobiss.backend.dto.roadmap.AskRequest;
import com.jobiss.backend.dto.roadmap.AskResponse;
import com.jobiss.backend.dto.roadmap.GenerateRoadmapRequest;
import com.jobiss.backend.dto.roadmap.ReassessRequest;
import com.jobiss.backend.dto.roadmap.RoadmapDetailResponse;
import com.jobiss.backend.dto.roadmap.SavedRoadmapResponse;
import com.jobiss.backend.dto.roadmap.StepProgressResponse;
import com.jobiss.backend.service.SavedRoadmapService;
import jakarta.validation.Valid;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
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

    /** 단건 조회(로드맵 페이지용) — GET /api/roadmaps/one?analysisId=&routeId= (로드맵 + 스텝 진행 상태) */
    @GetMapping("/one")
    public RoadmapDetailResponse one(@AuthenticationPrincipal Long userId,
                                     @RequestParam String analysisId, @RequestParam String routeId) {
        return savedRoadmapService.getOne(userId, analysisId, routeId);
    }

    /** 스텝 산출물 링크 제출 → 가짜 AI 재진단 → 진행 상태 저장. */
    @PostMapping("/reassess")
    public StepProgressResponse reassess(@AuthenticationPrincipal Long userId,
                                         @Valid @RequestBody ReassessRequest request) {
        return savedRoadmapService.reassess(userId, request);
    }

    /** 로드맵에 물어보기(가짜 AI 답변, 저장 없음). */
    @PostMapping("/ask")
    public AskResponse ask(@AuthenticationPrincipal Long userId,
                           @Valid @RequestBody AskRequest request) {
        return savedRoadmapService.ask(userId, request);
    }

    /** 대표 로드맵 지정(한 사용자에 하나). */
    @PostMapping("/{id}/representative")
    public SavedRoadmapResponse setRepresentative(@AuthenticationPrincipal Long userId, @PathVariable Long id) {
        return savedRoadmapService.setRepresentative(userId, id);
    }

    /** 저장 로드맵 삭제(+스텝 진행). */
    @DeleteMapping("/{id}")
    public java.util.Map<String, Object> delete(@AuthenticationPrincipal Long userId, @PathVariable Long id) {
        savedRoadmapService.deleteRoadmap(userId, id);
        return java.util.Map.of("deleted", true);
    }
}
