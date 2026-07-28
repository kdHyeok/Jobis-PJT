package com.jobiss.backend.service;

import com.jobiss.backend.domain.RoadmapStepProgress;
import com.jobiss.backend.domain.RoadmapStepStatus;
import com.jobiss.backend.domain.SavedRoadmap;
import com.jobiss.backend.dto.roadmap.AskRequest;
import com.jobiss.backend.dto.roadmap.AskResponse;
import com.jobiss.backend.dto.roadmap.GenerateRoadmapRequest;
import com.jobiss.backend.dto.roadmap.ReassessRequest;
import com.jobiss.backend.dto.roadmap.RoadmapDetailResponse;
import com.jobiss.backend.dto.roadmap.SavedRoadmapResponse;
import com.jobiss.backend.dto.roadmap.StepProgressResponse;
import com.jobiss.backend.exception.ApiException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
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

    /** 단건 조회(로드맵 페이지용) — 로드맵 + 스텝별 진행 상태를 함께. */
    public RoadmapDetailResponse getOne(Long userId, String analysisId, String routeId) {
        SavedRoadmap s = txService.findOne(userId, analysisId, routeId);
        List<StepProgressResponse> progress = txService.progressFor(userId, analysisId, routeId).stream()
                .map(SavedRoadmapService::toProgressResponse).toList();
        return new RoadmapDetailResponse(s.getId(), s.getAnalysisId(), s.getRouteId(),
                s.getGoalLabel(), s.getRoadmapJson(), s.isRepresentative(), progress);
    }

    /**
     * 스텝 산출물 링크 제출 → 가짜 AI 재진단 → 진행 상태 저장.
     * (읽기 tx: 로드맵 로드) → (tx 밖: 스텝 추출 + AI 호출) → (쓰기 tx: 진행 상태 교체).
     */
    public StepProgressResponse reassess(Long userId, ReassessRequest req) {
        if (!ALLOWED_ROUTES.contains(req.routeId())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_ROUTE", "이 경로로는 재진단할 수 없어요.");
        }
        SavedRoadmap saved = txService.findOne(userId, req.analysisId(), req.routeId());
        JsonNode step = extractStep(saved.getRoadmapJson(), req.stepNo());
        String verdictJson = callAgentReassess(req.routeId(), step, req.url());
        RoadmapStepStatus status = verdictStatus(verdictJson);
        RoadmapStepProgress p;
        try {
            p = txService.upsertProgress(
                    userId, req.analysisId(), req.routeId(), req.stepNo(), status, req.url(), verdictJson);
        } catch (DataIntegrityViolationException race) {
            // 같은 스텝 최초 동시 제출 경합(uk_step_progress 위반) — 새 트랜잭션으로 1회 재시도하면 기존 행을 찾아 갱신한다.
            p = txService.upsertProgress(
                    userId, req.analysisId(), req.routeId(), req.stepNo(), status, req.url(), verdictJson);
        }
        return toProgressResponse(p);
    }

    /** 대표 로드맵 지정. */
    public SavedRoadmapResponse setRepresentative(Long userId, Long id) {
        return toResponse(txService.setRepresentative(userId, id));
    }

    /** 저장 로드맵 삭제(+스텝 진행). */
    public void deleteRoadmap(Long userId, Long id) {
        txService.deleteRoadmap(userId, id);
    }

    /** 로드맵에 물어보기 — 저장된 로드맵 맥락(topGap·회사)을 실어 가짜 AI에 질문(DB 쓰기 없음). */
    public AskResponse ask(Long userId, AskRequest req) {
        if (!ALLOWED_ROUTES.contains(req.routeId())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_ROUTE", "이 경로로는 물어볼 수 없어요.");
        }
        SavedRoadmap saved = txService.findOne(userId, req.analysisId(), req.routeId());
        String topGap = "";
        String company = "";
        try {
            JsonNode root = om.readTree(saved.getRoadmapJson());
            topGap = root.path("topGap").asString("");
            company = root.path("title").asString("");
        } catch (Exception ignore) {
            // 맥락 파싱 실패해도 질문은 가능(가짜 AI가 일반 답변)
        }
        return new AskResponse(callAgentAsk(userId, req.routeId(), company, topGap, req.question()));
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

    /** 저장된 로드맵 JSON에서 stepNo 스텝 노드를 찾는다(재진단 맥락). */
    private JsonNode extractStep(String roadmapJson, int stepNo) {
        try {
            JsonNode steps = om.readTree(roadmapJson).path("steps");
            if (steps.isArray()) {
                for (int i = 0; i < steps.size(); i++) {
                    JsonNode st = steps.get(i);
                    if (st.path("no").asInt(-1) == stepNo) {
                        return st;
                    }
                }
            }
        } catch (Exception e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "ROADMAP_PARSE_FAILED",
                    "저장된 로드맵을 해석하지 못했어요.");
        }
        throw new ApiException(HttpStatus.NOT_FOUND, "STEP_NOT_FOUND", "로드맵에 해당 스텝이 없어요.");
    }

    /** 가짜 AI HTTP /reassess 호출 → 판정 JSON 문자열(그대로 저장·반환). */
    private String callAgentReassess(String routeKind, JsonNode step, String url) {
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("routeKind", routeKind);
            body.put("step", step);
            body.put("url", url);

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + "/reassess"))
                    .timeout(Duration.ofSeconds(15))
                    .header("Content-Type", "application/json; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();

            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_REASSESS_FAILED",
                        "AI 재진단 실패(" + response.statusCode() + ")");
            }
            return response.body();
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_UNREACHABLE",
                    "AI 서버에 연결하지 못했어요. (가짜 AI 서버가 켜져 있나요?)");
        }
    }

    /**
     * AI HTTP /roadmap-ask 호출 → 답변 텍스트.
     * userId 를 함께 보내면 AI 가 그 사용자 세션(분석·로드맵 자산)을 맥락으로 삼아
     * 오케스트레이터가 담당 에이전트를 고른다.
     */
    private String callAgentAsk(Long userId, String routeKind, String company, String topGap,
                                String question) {
        String respBody;
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("userId", userId);
            body.put("routeKind", routeKind);
            body.put("company", company);
            body.put("topGap", topGap);
            body.put("question", question);

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + "/roadmap-ask"))
                    .timeout(Duration.ofSeconds(15))
                    .header("Content-Type", "application/json; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();

            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_ASK_FAILED",
                        "AI 응답 실패(" + response.statusCode() + ")");
            }
            respBody = response.body();
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_UNREACHABLE",
                    "AI 서버에 연결하지 못했어요. (가짜 AI 서버가 켜져 있나요?)");
        }
        // 응답 파싱 실패는 '연결 실패'와 구분(진짜 AI가 다른 형태로 응답할 때 오진단 방지)
        try {
            return om.readTree(respBody).path("answer").asString("");
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_ASK_BAD_RESPONSE",
                    "AI 응답 형식이 올바르지 않아요.");
        }
    }

    /** 판정 JSON의 verdict 필드로 상태 매핑(verified → VERIFIED, 그 외 → NEEDS_WORK). */
    private RoadmapStepStatus verdictStatus(String verdictJson) {
        try {
            String v = om.readTree(verdictJson).path("verdict").asString("insufficient");
            return "verified".equals(v) ? RoadmapStepStatus.VERIFIED : RoadmapStepStatus.NEEDS_WORK;
        } catch (Exception e) {
            return RoadmapStepStatus.NEEDS_WORK;
        }
    }

    private static StepProgressResponse toProgressResponse(RoadmapStepProgress p) {
        return new StepProgressResponse(p.getStepNo(), p.getStatus().name(), p.getSubmittedUrl(), p.getVerdictJson());
    }
}
