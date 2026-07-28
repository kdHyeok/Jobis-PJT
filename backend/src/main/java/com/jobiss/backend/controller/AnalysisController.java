package com.jobiss.backend.controller;

import com.jobiss.backend.dto.analysis.AnalysisStatusResponse;
import com.jobiss.backend.dto.analysis.AnalysisSummaryResponse;
import com.jobiss.backend.dto.analysis.CustomAnalysisRequest;
import com.jobiss.backend.dto.analysis.ResultResponse;
import com.jobiss.backend.dto.analysis.SelectRouteRequest;
import com.jobiss.backend.service.AnalysisDeletionService;
import com.jobiss.backend.service.AnalysisService;
import com.jobiss.backend.service.agent.AgentRunService;
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
import java.util.Map;

@RestController
@RequestMapping("/api/analyses")
public class AnalysisController {

    private final AnalysisService analysisService;
    private final AgentRunService agentRunService;
    private final AnalysisDeletionService deletionService;

    public AnalysisController(AnalysisService analysisService, AgentRunService agentRunService,
                             AnalysisDeletionService deletionService) {
        this.analysisService = analysisService;
        this.agentRunService = agentRunService;
        this.deletionService = deletionService;
    }

    /**
     * 자유 입력 공고로 분석 준비(Run 생성). 웹은 원문만 담고 파싱하지 않는다.
     * 실제 AI 세션은 브라우저가 구독을 마친 뒤 /agent/{analysisId}/begin 으로 시작한다.
     */
    @PostMapping("/agent-custom")
    public Map<String, String> startAgentCustom(@AuthenticationPrincipal Long userId,
                                                @Valid @RequestBody CustomAnalysisRequest request) {
        String analysisId = agentRunService.createCustomRun(userId, request);
        return Map.of("analysisId", analysisId);
    }

    /** 브라우저가 /topic/analysis/{id} 구독을 마친 뒤 호출 → AI 세션 시작(초기 신호 유실 방지). */
    @PostMapping("/agent/{analysisId}/begin")
    public Map<String, String> beginAgent(@AuthenticationPrincipal Long userId,
                                          @PathVariable String analysisId) {
        agentRunService.beginSession(userId, analysisId);
        return Map.of("status", "started");
    }

    /** 사이드바 "최근 분석" 목록(내 분석, 최신순). */
    @GetMapping
    public List<AnalysisSummaryResponse> list(@AuthenticationPrincipal Long userId) {
        return analysisService.listForUser(userId);
    }

    /** 진행 상태 폴링. */
    @GetMapping("/{analysisId}")
    public AnalysisStatusResponse status(@AuthenticationPrincipal Long userId, @PathVariable String analysisId) {
        return analysisService.getStatus(userId, analysisId);
    }

    /** 결과 보고서 조회. */
    @GetMapping("/{analysisId}/result")
    public ResultResponse result(@AuthenticationPrincipal Long userId, @PathVariable String analysisId) {
        return analysisService.getResult(userId, analysisId);
    }

    /** 경로 비교에서 주 경로 선택 저장(스펙 §11.3). 재선택 가능. */
    @PostMapping("/{analysisId}/selected-route")
    public Map<String, String> selectRoute(@AuthenticationPrincipal Long userId, @PathVariable String analysisId,
                                           @Valid @RequestBody SelectRouteRequest request) {
        analysisService.selectRoute(userId, analysisId, request.routeId());
        return Map.of("status", "ok");
    }

    /** 삭제 미리보기 — 함께 지워질 자식 재분석·저장 로드맵 수(확인창용). */
    @GetMapping("/{analysisId}/deletion-preview")
    public Map<String, Object> deletionPreview(@AuthenticationPrincipal Long userId, @PathVariable String analysisId) {
        return deletionService.preview(userId, analysisId);
    }

    /** 분석 삭제(자식 재분석 연쇄). deleteRoadmaps=false면 저장 로드맵은 남긴다(고아). */
    @DeleteMapping("/{analysisId}")
    public Map<String, Object> delete(@AuthenticationPrincipal Long userId, @PathVariable String analysisId,
                                      @RequestParam(defaultValue = "true") boolean deleteRoadmaps) {
        return deletionService.delete(userId, analysisId, deleteRoadmaps);
    }
}
