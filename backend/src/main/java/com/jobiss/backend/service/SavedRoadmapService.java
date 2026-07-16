package com.jobiss.backend.service;

import com.jobiss.backend.domain.SavedRoadmap;
import com.jobiss.backend.dto.roadmap.GenerateRoadmapRequest;
import com.jobiss.backend.dto.roadmap.SavedRoadmapResponse;
import com.jobiss.backend.exception.ApiException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 로드맵 생성(저장) — 웹은 "전달만": (분석 + 경로 + 목표 맥락)을 가짜 AI(HTTP /roadmap)에 넘겨
 * 로드맵을 정리받고 저장한다. 목표 맥락(부모)이 있으면 "디딤돌" 로드맵이 나온다.
 *
 * 트랜잭션 경계: DB 읽기/쓰기는 RoadmapTxService(짧은 트랜잭션)에 두고,
 * 느릴 수 있는 AI HTTP 호출은 트랜잭션 밖에서 한다(커넥션 풀 점유 방지).
 * 진짜 AI가 생기면 http-url 만 바꾸면 된다(계약 동일).
 */
@Service
public class SavedRoadmapService {

    private static final Set<String> ALLOWED_ROUTES = Set.of("as_is", "reinforce");

    private final RoadmapTxService txService;
    private final ObjectMapper om;
    private final String agentHttpUrl;
    // HTTP/1.1 고정: 기본 HTTP/2는 'Upgrade: h2c' 를 보내 가짜 AI(ws가 붙은 http)가 405로 막는다.
    private final HttpClient httpClient = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    public SavedRoadmapService(RoadmapTxService txService, ObjectMapper om,
                               @Value("${jobiss.agent.http-url}") String agentHttpUrl) {
        this.txService = txService;
        this.om = om;
        this.agentHttpUrl = agentHttpUrl;
    }

    /** (분석·경로)로 로드맵 생성 → 저장. AI HTTP 호출은 DB 트랜잭션 밖에서. */
    public SavedRoadmapResponse generate(Long userId, GenerateRoadmapRequest req) {
        if (!ALLOWED_ROUTES.contains(req.routeId())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_ROUTE", "이 경로로는 로드맵을 생성할 수 없어요.");
        }
        // 1) 읽기 트랜잭션: 소유권 확인 + AI 호출 맥락
        RoadmapTxService.RoadmapContext ctx = txService.load(userId, req.analysisId(), req.routeId());
        // 2) 트랜잭션 밖: 가짜 AI 로드맵 생성
        String roadmapJson = callAgentRoadmap(ctx.company(), ctx.role(), ctx.routeKind(), ctx.goalCompany());
        // 3) 쓰기 트랜잭션: 저장(같은 조합이면 교체)
        SavedRoadmap saved = txService.upsert(userId, req.analysisId(), req.routeId(), ctx.goalLabel(), roadmapJson);
        return toResponse(saved);
    }

    /** 로드맵 저장소 목록(내 것, 최신순). */
    public List<SavedRoadmapResponse> list(Long userId) {
        return txService.listForUser(userId).stream().map(SavedRoadmapService::toResponse).toList();
    }

    /** 대표 로드맵 지정. */
    public SavedRoadmapResponse setRepresentative(Long userId, Long id) {
        return toResponse(txService.setRepresentative(userId, id));
    }

    private static SavedRoadmapResponse toResponse(SavedRoadmap s) {
        return new SavedRoadmapResponse(s.getId(), s.getAnalysisId(), s.getRouteId(),
                s.getGoalLabel(), s.getRoadmapJson(), s.isRepresentative());
    }

    /** 가짜 AI HTTP /roadmap 호출 → 로드맵 JSON 문자열(그대로 저장·반환). */
    private String callAgentRoadmap(String company, String role, String routeKind, String goalCompany) {
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("company", company == null ? "" : company);
            body.put("role", role == null ? "" : role);
            body.put("routeKind", routeKind);
            body.put("goalCompany", goalCompany);   // null 허용(독립 목표)

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + "/roadmap"))
                    .timeout(Duration.ofSeconds(15))
                    .header("Content-Type", "application/json; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();

            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_ROADMAP_FAILED",
                        "AI 로드맵 생성 실패(" + response.statusCode() + ")");
            }
            return response.body();
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_UNREACHABLE",
                    "AI 서버에 연결하지 못했어요. (가짜 AI 서버가 켜져 있나요?)");
        }
    }
}
