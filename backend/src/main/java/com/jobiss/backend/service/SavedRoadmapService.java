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
import com.jobiss.backend.dto.roadmap.StageDetailResponse;
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
        // 2) 트랜잭션 밖: 가짜 AI 로드맵 생성.
        //    보강 경로(reinforce) = 단계형(staged) 개요(상세는 열람 시 lazy). 즉시 지원(as_is) = 기존 평면 로드맵.
        String roadmapJson;
        if ("reinforce".equals(req.routeId())) {
            RoadmapTxService.StagedContext sc = txService.loadStaged(userId, req.analysisId());
            roadmapJson = callAgentRoadmapStages(assembleStagedInput(sc));
        } else {
            roadmapJson = callAgentRoadmap(ctx.company(), ctx.role(), ctx.routeKind(), ctx.goalCompany());
        }
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
     * 단계형 로드맵의 한 단계 상세(레슨·예제·결과물·시험) — 그 단계를 열 때 호출.
     * 캐시(roadmap_stage_details)에 있으면 즉시, 없으면 개요에서 goal+stage 뽑아 가짜 AI 생성 후 캐시.
     */
    public StageDetailResponse stageDetail(Long userId, String analysisId, String routeId, int stageNo) {
        SavedRoadmap saved = txService.findOne(userId, analysisId, routeId);   // 소유권 확인 + 개요 로드
        var cached = txService.findDetail(saved.getId(), stageNo);
        if (cached.isPresent()) {
            return new StageDetailResponse(stageNo, cached.get().getDetailJson());
        }
        JsonNode outline;
        try {
            outline = om.readTree(saved.getRoadmapJson());
        } catch (Exception e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "ROADMAP_PARSE_FAILED", "저장된 로드맵을 해석하지 못했어요.");
        }
        JsonNode goal = outline.path("goal");
        JsonNode stage = null;
        JsonNode stages = outline.path("stages");
        if (stages.isArray()) {
            for (JsonNode s : stages) {
                if (s.path("no").asInt(-1) == stageNo) { stage = s; break; }
            }
        }
        if (stage == null) {
            throw new ApiException(HttpStatus.NOT_FOUND, "STAGE_NOT_FOUND", "로드맵에 해당 단계가 없어요.");
        }
        String detailJson = callAgentStageDetail(goal, stage);   // 트랜잭션 밖: 느린 AI 호출
        txService.saveDetail(saved.getId(), stageNo, detailJson);
        return new StageDetailResponse(stageNo, detailJson);
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
        return new AskResponse(callAgentAsk(req.routeId(), company, topGap, req.question()));
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
                    .timeout(Duration.ofSeconds(150))   // 진짜 Claude 호출이라 길게
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

    /** 가짜 AI HTTP /roadmap-stages 호출 → 단계형 개요 JSON(그대로 저장). */
    private String callAgentRoadmapStages(Map<String, Object> input) {
        return postAgent("/roadmap-stages", input, 90, "AI_STAGED_FAILED", "AI 단계형 로드맵 생성 실패");
    }

    /** 가짜 AI HTTP /roadmap-stage-detail 호출 → 단계 상세 JSON. (뼈대+레슨상세라 길게 대기) */
    private String callAgentStageDetail(JsonNode goal, JsonNode stage) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("goal", goal);
        body.put("stage", stage);
        return postAgent("/roadmap-stage-detail", body, 260, "AI_STAGE_DETAIL_FAILED", "AI 단계 상세 생성 실패");
    }

    /** 공통 POST(가짜 AI). timeoutSec 만큼 대기 — 진짜 Claude 호출이라 길다. */
    private String postAgent(String path, Object body, int timeoutSec, String failCode, String failMsg) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + path))
                    .timeout(Duration.ofSeconds(timeoutSec))
                    .header("Content-Type", "application/json; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, failCode, failMsg + "(" + response.statusCode() + ")");
            }
            return response.body();
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_UNREACHABLE",
                    "AI 서버에 연결하지 못했어요. (가짜 AI 서버가 켜져 있나요?)");
        }
    }

    /** 분석 결과(격차·판정)에서 staged 개요 입력을 조립한다. gap.requirement 가 곧 공고 요건. */
    private Map<String, Object> assembleStagedInput(RoadmapTxService.StagedContext sc) {
        Map<String, Object> input = new LinkedHashMap<>();
        input.put("company", sc.company() == null ? "" : sc.company());
        input.put("role", sc.role() == null ? "" : sc.role());
        List<Map<String, Object>> gaps = new java.util.ArrayList<>();
        List<Map<String, Object>> requirements = new java.util.ArrayList<>();
        String userState = "";
        try {
            JsonNode root = om.readTree(sc.resultJson() == null ? "{}" : sc.resultJson());
            userState = root.path("readiness").path("judge")
                    .asString(root.path("decision").path("headline").asString(""));
            JsonNode gapsNode = root.path("gaps");
            if (gapsNode.isArray()) {
                for (JsonNode g : gapsNode) {
                    String requirement = g.path("requirement").asString("");
                    if (requirement.isBlank()) continue;
                    Map<String, Object> gap = new LinkedHashMap<>();
                    gap.put("requirement", requirement);
                    gap.put("mark", g.path("mark").asString(""));
                    gap.put("fix", g.path("fix").asString(g.path("evidence").asString("")));
                    gaps.add(gap);
                    Map<String, Object> reqm = new LinkedHashMap<>();
                    reqm.put("type", requirement.startsWith("우대") ? "우대" : "필수");
                    reqm.put("quote", requirement);
                    requirements.add(reqm);
                }
            }
        } catch (Exception ignore) {
            // 결과 파싱 실패해도 개요는 회사·직무만으로 생성 가능(가짜 AI가 기본값 처리)
        }
        // 지망 트랙(현재 미포착) — 직무·요건 텍스트로 가볍게 추정.
        String hay = (sc.role() == null ? "" : sc.role()) + " " + requirements;
        String track = "";
        if (hay.matches("(?s).*(백엔드|Spring|Java|서버|API).*")) track = "Java/Spring 백엔드 중심";
        else if (hay.matches("(?s).*(프론트|React|Next|Vue|CSS).*")) track = "프론트엔드 중심";
        input.put("track", track);
        input.put("requirements", requirements);
        input.put("gaps", gaps);
        input.put("userState", userState);
        return input;
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
                    .timeout(Duration.ofSeconds(150))   // 진짜 Claude 호출이라 길게
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

    /** 가짜 AI HTTP /roadmap-ask 호출 → 답변 텍스트. */
    private String callAgentAsk(String routeKind, String company, String topGap, String question) {
        String respBody;
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("routeKind", routeKind);
            body.put("company", company);
            body.put("topGap", topGap);
            body.put("question", question);

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + "/roadmap-ask"))
                    .timeout(Duration.ofSeconds(150))   // 진짜 Claude 호출이라 길게
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
