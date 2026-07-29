package com.jobiss.backend.controller;

import com.jobiss.backend.service.DevResetService;
import com.jobiss.backend.service.agent.AgentRunService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 개발용 트리거. 배포 전 제거.
 * POST /api/dev/agent-run — 가짜 AI 에이전트 분석 세션을 시작한다.
 * POST /api/dev/reset?email=... — 그 계정과 모든 데이터를 초기화(시연 반복용).
 */
@RestController
@RequestMapping("/api/dev")
public class DevController {

    private final AgentRunService agentRunService;
    private final DevResetService devResetService;

    public DevController(AgentRunService agentRunService, DevResetService devResetService) {
        this.agentRunService = agentRunService;
        this.devResetService = devResetService;
    }

    /** 시연 반복용: 이메일 계정 + 모든 데이터 초기화. 이후 같은 이메일로 재가입하면 빈 상태부터 시작. */
    @PostMapping("/reset")
    public Map<String, Object> reset(@RequestParam String email) {
        return devResetService.resetByEmail(email);
    }

    @PostMapping("/agent-run")
    public Map<String, String> agentRun(@RequestBody(required = false) AgentRunRequest request) {
        String code = (request != null && request.jobPostingCode() != null) ? request.jobPostingCode() : "cloudwave";
        List<Long> ids = (request != null) ? request.evidenceIds() : null;
        String analysisId = agentRunService.startDemoRun(code, ids);
        return Map.of(
                "analysisId", analysisId,
                "message", "가짜 AI 세션을 시작했습니다. 백엔드 콘솔 로그(PROGRESS/QUESTION/DONE)를 확인하세요."
        );
    }

    public record AgentRunRequest(String jobPostingCode, List<Long> evidenceIds) {
    }
}
