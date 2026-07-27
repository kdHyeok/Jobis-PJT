package com.jobiss.backend.service;

import com.jobiss.backend.domain.Evidence;
import com.jobiss.backend.domain.EvidenceKind;
import com.jobiss.backend.domain.EvidenceStatus;
import com.jobiss.backend.domain.User;
import com.jobiss.backend.dto.evidence.BulkImportRequest;
import com.jobiss.backend.dto.evidence.BulkImportResponse;
import com.jobiss.backend.dto.evidence.EvidenceCreateRequest;
import com.jobiss.backend.dto.evidence.EvidenceResponse;
import com.jobiss.backend.dto.evidence.ImportParseFileRequest;
import com.jobiss.backend.dto.evidence.ImportParseFileResponse;
import com.jobiss.backend.dto.evidence.ImportParseRequest;
import com.jobiss.backend.dto.evidence.ImportParseResponse;
import com.jobiss.backend.dto.evidence.ParsedFragment;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.repository.EvidenceRepository;
import com.jobiss.backend.repository.UserRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 커리어 저장소 자료 파편화 — 웹은 "원문 전달"만 하고, 실제 파싱은 가짜 AI(HTTP /extract)가 한다.
 *   parse()          : 가짜 AI에 파싱 요청 → 받은 조각에 STACK 중복표시(데이터 의존 로직은 웹 유지) → 반환(저장 안 함)
 *   importSelected() : 사용자가 확인·선택한 조각을 저장(STACK은 저장 시에도 방어적 중복제거)
 * 진짜 AI가 생기면 http-url 만 바꾸면 된다(계약 동일).
 */
@Service
public class EvidenceImportService {

    private final EvidenceRepository evidenceRepository;
    private final UserRepository userRepository;
    private final ObjectMapper om;
    private final String agentHttpUrl;
    // HTTP/1.1 고정: 기본 HTTP/2 클라이언트는 'Upgrade: h2c' 헤더를 보내는데,
    // 가짜 AI(ws 라이브러리가 붙은 http 서버)가 이를 업그레이드로 오인해 405로 막는다.
    private final HttpClient httpClient = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    public EvidenceImportService(EvidenceRepository evidenceRepository, UserRepository userRepository,
                                 ObjectMapper om, @Value("${jobiss.agent.http-url}") String agentHttpUrl) {
        this.evidenceRepository = evidenceRepository;
        this.userRepository = userRepository;
        this.om = om;
        this.agentHttpUrl = agentHttpUrl;
    }

    /** 파싱(등록 아님): 가짜 AI가 조각을 만들고, 웹이 저장소 대조로 STACK duplicate 를 표시. */
    @Transactional(readOnly = true)
    public ImportParseResponse parse(Long userId, ImportParseRequest req) {
        List<RawFragment> raw = callAgentExtract(req.sourceType(), req.content());

        Set<String> existingStacks = evidenceRepository.findByUserId(userId).stream()
                .filter(e -> e.getKind() == EvidenceKind.STACK)
                .map(e -> e.getLabel().toLowerCase(Locale.ROOT))
                .collect(Collectors.toSet());

        return new ImportParseResponse(toFragments(raw, existingStacks));
    }

    /**
     * 이력서 파일 파싱(등록 아님). pdf·docx 처럼 브라우저가 읽을 수 없는 형식을 위해
     * 파일 바이트를 AI(브릿지)로 보내 원문과 조각을 함께 받는다.
     */
    @Transactional(readOnly = true)
    public ImportParseFileResponse parseFile(Long userId, ImportParseFileRequest req) {
        FileExtract extracted = callAgentExtractFile(req.filename(), req.contentBase64());

        Set<String> existingStacks = evidenceRepository.findByUserId(userId).stream()
                .filter(e -> e.getKind() == EvidenceKind.STACK)
                .map(e -> e.getLabel().toLowerCase(Locale.ROOT))
                .collect(Collectors.toSet());

        return new ImportParseFileResponse(extracted.text(),
                toFragments(extracted.fragments(), existingStacks));
    }

    /** 조각 원본 → 후보 목록. 결과 내 STACK 중복 제거 + 저장소에 이미 있는 STACK 표시. */
    private List<ParsedFragment> toFragments(List<RawFragment> raw, Set<String> existingStacks) {
        Set<String> seenStack = new HashSet<>();
        List<ParsedFragment> out = new ArrayList<>();
        for (RawFragment f : raw) {
            if (f.kind() == EvidenceKind.STACK) {
                String key = f.label().toLowerCase(Locale.ROOT);
                if (!seenStack.add(key)) continue;   // 결과 내 STACK 중복 제거
                boolean dup = existingStacks.contains(key);
                out.add(new ParsedFragment(EvidenceKind.STACK, f.label(), f.description(), dup));
            } else {
                out.add(new ParsedFragment(f.kind(), f.label(), f.description(), false));   // 나머지는 누적
            }
        }
        return out;
    }

    /** 확인·선택한 조각들을 실제 등록. STACK은 저장 시에도 방어적으로 중복 제거. */
    @Transactional
    public BulkImportResponse importSelected(Long userId, BulkImportRequest req) {
        User userRef = userRepository.getReferenceById(userId);

        Set<String> stackLabels = evidenceRepository.findByUserId(userId).stream()
                .filter(e -> e.getKind() == EvidenceKind.STACK)
                .map(e -> e.getLabel().toLowerCase(Locale.ROOT))
                .collect(Collectors.toCollection(HashSet::new));

        List<EvidenceResponse> created = new ArrayList<>();
        int skipped = 0;
        for (EvidenceCreateRequest item : req.items()) {
            if (item.kind() == EvidenceKind.STACK) {
                String key = item.label().trim().toLowerCase(Locale.ROOT);
                if (!stackLabels.add(key)) { skipped++; continue; }
            }
            Evidence saved = evidenceRepository.save(Evidence.builder()
                    .user(userRef)
                    .kind(item.kind())
                    .label(cap(item.label().trim(), 255))   // label 컬럼 길이 방어
                    .description(item.description())
                    .status(EvidenceStatus.OK)
                    .build());
            created.add(EvidenceResponse.from(saved));
        }
        return new BulkImportResponse(created, skipped);
    }

    /** 가짜 AI HTTP /extract 호출 → 조각 원본 목록. */
    @SuppressWarnings("unchecked")
    private List<RawFragment> callAgentExtract(String sourceType, String content) {
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("sourceType", sourceType == null ? "TEXT" : sourceType);
            body.put("content", content == null ? "" : content);

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + "/extract"))
                    .timeout(Duration.ofSeconds(15))
                    .header("Content-Type", "application/json; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();

            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PARSE_FAILED",
                        "AI 파싱 실패(" + response.statusCode() + ")");
            }

            Map<String, Object> parsed = om.readValue(response.body(), Map.class);
            Object fragsObj = parsed.get("fragments");
            List<RawFragment> list = new ArrayList<>();
            if (fragsObj instanceof List<?> frags) {
                for (Object o : frags) {
                    if (!(o instanceof Map<?, ?> f)) continue;
                    EvidenceKind kind = parseKind(f.get("kind"));
                    String label = str(f.get("label")).trim();
                    if (kind == null || label.isEmpty()) continue;
                    list.add(new RawFragment(kind, cap(label, 255), str(f.get("description"))));
                }
            }
            return list;
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_UNREACHABLE",
                    "AI 서버에 연결하지 못했어요. (가짜 AI 서버가 켜져 있나요?)");
        }
    }

    /** AI HTTP /extract-file 호출 → (이력서 원문, 조각 원본). */
    @SuppressWarnings("unchecked")
    private FileExtract callAgentExtractFile(String filename, String contentBase64) {
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("filename", filename == null ? "" : filename);
            body.put("contentBase64", contentBase64 == null ? "" : contentBase64);

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + "/extract-file"))
                    // 파일 추출 + 조각 생성(LLM)까지 하므로 텍스트 파싱보다 넉넉히 준다.
                    .timeout(Duration.ofSeconds(120))
                    .header("Content-Type", "application/json; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();

            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_PARSE_FAILED",
                        "이력서 파일 파싱 실패(" + response.statusCode() + ")");
            }

            Map<String, Object> parsed = om.readValue(response.body(), Map.class);
            String text = str(parsed.get("text"));
            List<RawFragment> list = new ArrayList<>();
            if (parsed.get("fragments") instanceof List<?> frags) {
                for (Object o : frags) {
                    if (!(o instanceof Map<?, ?> f)) continue;
                    EvidenceKind kind = parseKind(f.get("kind"));
                    String label = str(f.get("label")).trim();
                    if (kind == null || label.isEmpty()) continue;
                    list.add(new RawFragment(kind, cap(label, 255), str(f.get("description"))));
                }
            }
            if (text.isBlank()) {
                // AI 가 남긴 사유(미지원 확장자·글자 없음 등)를 그대로 전달한다 — 사용자가 다음 행동을 알 수 있게.
                String reason = "파일에서 글자를 찾지 못했어요. 스캔 이미지 PDF 라면 원문을 붙여 넣어 주세요.";
                if (parsed.get("warnings") instanceof List<?> warns && !warns.isEmpty()
                        && warns.get(0) instanceof Map<?, ?> w0 && !str(w0.get("message")).isBlank()) {
                    reason = str(w0.get("message"));
                }
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "EMPTY_RESUME", reason);
            }
            return new FileExtract(text, list);
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_UNREACHABLE",
                    "AI 서버에 연결하지 못했어요. (웹 브릿지가 켜져 있나요?)");
        }
    }

    private record FileExtract(String text, List<RawFragment> fragments) {
    }

    private static EvidenceKind parseKind(Object kind) {
        if (kind == null) return null;
        try {
            return EvidenceKind.valueOf(String.valueOf(kind).trim().toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException e) {
            return null;
        }
    }

    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static String cap(String s, int n) {
        if (s == null) return null;
        return s.length() > n ? s.substring(0, n) : s;
    }

    /** 가짜 AI가 준 조각 원본(중복표시 전). */
    private record RawFragment(EvidenceKind kind, String label, String description) {
    }
}
