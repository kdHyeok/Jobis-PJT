package com.jobiss.repository;

import com.jobiss.analysis.AiContracts;
import com.jobiss.common.ApiException;
import com.jobiss.config.RepositoryProperties;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

@Component
public class RepositoryEvidenceCollector {

    private static final int MAX_FILES = 28;
    private static final int MAX_FILE_CHARS = 40_000;
    private static final int MAX_TOTAL_CHARS = 350_000;
    private static final int MAX_TREE_ITEMS = 2_000;

    private final RepositoryConnectionService connections;
    private final RepositoryProperties properties;
    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;
    private final RestClient http = RestClient.builder().build();

    public RepositoryEvidenceCollector(
            RepositoryConnectionService connections,
            RepositoryProperties properties,
            RlsTransactionExecutor rls,
            ObjectMapper objectMapper
    ) {
        this.connections = connections;
        this.properties = properties;
        this.rls = rls;
        this.objectMapper = objectMapper;
    }

    public AiContracts.EvidencePayload enrich(
            UUID userId,
            AiContracts.EvidencePayload evidence
    ) {
        RepositoryRef repository = parse(evidence.sourceUrl());
        if ("PROJECT".equalsIgnoreCase(evidence.evidenceType()) && repository == null) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "REPOSITORY_URL_REQUIRED",
                    "프로젝트 검증에는 GitHub 또는 설정된 GitLab 저장소 URL이 필요합니다."
            );
        }
        if (repository == null) return evidence;
        RepositoryConnectionService.RepositoryAccess access =
                connections.access(userId, repository.provider(), repository.baseUrl());
        Snapshot snapshot;
        try {
            snapshot = "GITHUB".equals(repository.provider())
                    ? collectGitHub(repository, access.token())
                    : collectGitLab(repository, access.token());
        } catch (RestClientException exception) {
            throw new ApiException(
                    HttpStatus.BAD_GATEWAY,
                    "REPOSITORY_SNAPSHOT_FAILED",
                    access.token() == null
                            ? "저장소를 읽지 못했습니다. 비공개 저장소라면 설정에서 읽기 전용 연결을 추가해 주세요."
                            : "연결된 저장소의 현재 커밋을 읽지 못했습니다. 권한과 저장소 주소를 확인해 주세요."
            );
        }

        ObjectNode collected = objectMapper.createObjectNode();
        collected.put("provider", repository.provider());
        collected.put("repositoryFullName", repository.fullName());
        collected.put("commitSha", snapshot.commitSha());
        collected.put("defaultBranch", snapshot.defaultBranch());
        collected.put("treeItemCount", snapshot.treeItemCount());
        collected.put("treeTruncated", snapshot.treeTruncated());
        collected.put("capturedFileCount", snapshot.files().size());
        ArrayNode files = collected.putArray("files");
        for (CapturedFile file : snapshot.files()) {
            ObjectNode item = files.addObject();
            item.put("path", file.path());
            item.put("content", file.content());
            item.put("truncated", file.truncated());
        }
        saveSnapshot(
                userId,
                evidence.id(),
                access.connectionId(),
                repository,
                snapshot,
                collected
        );

        ObjectNode enriched = objectMapper.createObjectNode();
        enriched.set("submittedEvidence", evidence.content());
        enriched.set("repositorySnapshot", collected);
        return new AiContracts.EvidencePayload(
                evidence.id(),
                evidence.evidenceType(),
                evidence.title(),
                evidence.sourceUrl(),
                enriched
        );
    }

    public boolean supports(String sourceUrl) {
        return parse(sourceUrl) != null;
    }

    private Snapshot collectGitHub(RepositoryRef repository, String token) {
        String api = stripTrailingSlash(properties.github().apiBaseUrl());
        JsonNode metadata = githubGet(api + "/repos/" + repository.fullName(), token);
        String branch = metadata.path("default_branch").stringValue("main");
        JsonNode commit = githubGet(
                api + "/repos/" + repository.fullName() + "/commits/" + encode(branch),
                token
        );
        String sha = commit.path("sha").stringValue();
        JsonNode tree = githubGet(
                api + "/repos/" + repository.fullName()
                        + "/git/trees/" + encode(sha) + "?recursive=1",
                token
        );
        List<TreeFile> candidates = new ArrayList<>();
        int treeCount = 0;
        for (JsonNode item : tree.path("tree")) {
            treeCount += 1;
            if (treeCount > MAX_TREE_ITEMS) break;
            if (!"blob".equals(item.path("type").stringValue())) continue;
            String path = item.path("path").stringValue();
            if (!isReadableCandidate(path, item.path("size").asLong(0))) continue;
            candidates.add(new TreeFile(
                    path,
                    item.path("sha").stringValue(),
                    priority(path)
            ));
        }
        candidates.sort(Comparator.comparingInt(TreeFile::priority).reversed()
                .thenComparing(TreeFile::path));
        List<CapturedFile> files = new ArrayList<>();
        int total = 0;
        for (TreeFile candidate : candidates) {
            if (files.size() >= MAX_FILES || total >= MAX_TOTAL_CHARS) break;
            JsonNode blob = githubGet(
                    api + "/repos/" + repository.fullName()
                            + "/git/blobs/" + encode(candidate.sha()),
                    token
            );
            if (!"base64".equals(blob.path("encoding").stringValue())) continue;
            String decoded;
            try {
                decoded = new String(
                        Base64.getMimeDecoder().decode(blob.path("content").stringValue()),
                        StandardCharsets.UTF_8
                );
            } catch (IllegalArgumentException ignored) {
                continue;
            }
            CapturedFile captured = capture(candidate.path(), decoded, MAX_TOTAL_CHARS - total);
            if (captured == null) break;
            files.add(captured);
            total += captured.content().length();
        }
        return new Snapshot(
                sha, branch, treeCount,
                tree.path("truncated").asBoolean(false) || treeCount > MAX_TREE_ITEMS,
                List.copyOf(files)
        );
    }

    private Snapshot collectGitLab(RepositoryRef repository, String token) {
        String api = stripTrailingSlash(repository.baseUrl()) + "/api/v4";
        String project = encode(repository.fullName());
        JsonNode metadata = gitlabGet(api + "/projects/" + project, token);
        String branch = metadata.path("default_branch").stringValue("main");
        JsonNode commit = gitlabGet(
                api + "/projects/" + project + "/repository/commits/" + encode(branch),
                token
        );
        String sha = commit.path("id").stringValue();
        JsonNode tree = gitlabGet(
                api + "/projects/" + project
                        + "/repository/tree?recursive=true&per_page=100&ref=" + encode(sha),
                token
        );
        List<TreeFile> candidates = new ArrayList<>();
        int treeCount = 0;
        for (JsonNode item : tree) {
            treeCount += 1;
            if (!"blob".equals(item.path("type").stringValue())) continue;
            String path = item.path("path").stringValue();
            if (!isReadableCandidate(path, 0)) continue;
            candidates.add(new TreeFile(path, item.path("id").stringValue(), priority(path)));
        }
        candidates.sort(Comparator.comparingInt(TreeFile::priority).reversed()
                .thenComparing(TreeFile::path));
        List<CapturedFile> files = new ArrayList<>();
        int total = 0;
        for (TreeFile candidate : candidates) {
            if (files.size() >= MAX_FILES || total >= MAX_TOTAL_CHARS) break;
            String content = gitlabGetText(
                    api + "/projects/" + project + "/repository/files/"
                            + encode(candidate.path()) + "/raw?ref=" + encode(sha),
                    token
            );
            CapturedFile captured = capture(candidate.path(), content, MAX_TOTAL_CHARS - total);
            if (captured == null) break;
            files.add(captured);
            total += captured.content().length();
        }
        return new Snapshot(sha, branch, treeCount, treeCount >= 100, List.copyOf(files));
    }

    private JsonNode githubGet(String url, String token) {
        RestClient.RequestHeadersSpec<?> request = http.get()
                .uri(url)
                .header(HttpHeaders.ACCEPT, "application/vnd.github+json");
        if (token != null) request = request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        return request.retrieve().body(JsonNode.class);
    }

    private JsonNode gitlabGet(String url, String token) {
        RestClient.RequestHeadersSpec<?> request = http.get().uri(url);
        if (token != null) request = request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        return request.retrieve().body(JsonNode.class);
    }

    private String gitlabGetText(String url, String token) {
        RestClient.RequestHeadersSpec<?> request = http.get().uri(url);
        if (token != null) request = request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        return request.retrieve().body(String.class);
    }

    private CapturedFile capture(String path, String content, int remaining) {
        if (content == null || remaining <= 0 || content.indexOf('\0') >= 0) return null;
        int limit = Math.min(MAX_FILE_CHARS, remaining);
        boolean truncated = content.length() > limit;
        return new CapturedFile(
                path,
                truncated ? content.substring(0, limit) : content,
                truncated
        );
    }

    private boolean isReadableCandidate(String path, long size) {
        if (size > 300_000) return false;
        String lower = path.toLowerCase(Locale.ROOT);
        if (lower.contains("node_modules/") || lower.contains("dist/")
                || lower.contains("build/") || lower.contains("vendor/")) return false;
        String name = lower.substring(lower.lastIndexOf('/') + 1);
        return name.startsWith("readme")
                || name.equals("dockerfile")
                || name.equals("pom.xml")
                || name.endsWith(".gradle")
                || name.endsWith(".gradle.kts")
                || name.equals("package.json")
                || name.equals("pyproject.toml")
                || name.equals("requirements.txt")
                || name.endsWith(".java") || name.endsWith(".kt")
                || name.endsWith(".py") || name.endsWith(".ts")
                || name.endsWith(".tsx") || name.endsWith(".js")
                || name.endsWith(".vue") || name.endsWith(".sql")
                || name.endsWith(".yml") || name.endsWith(".yaml")
                || name.endsWith(".md");
    }

    private int priority(String path) {
        String lower = path.toLowerCase(Locale.ROOT);
        String name = lower.substring(lower.lastIndexOf('/') + 1);
        if (name.startsWith("readme")) return 100;
        if (name.equals("pom.xml") || name.equals("package.json")
                || name.endsWith(".gradle") || name.endsWith(".gradle.kts")
                || name.equals("pyproject.toml")) return 95;
        if (lower.startsWith(".github/workflows/") || lower.contains(".gitlab-ci")) return 90;
        if (lower.contains("test") || lower.contains("spec")) return 80;
        if (name.equals("dockerfile") || lower.contains("docker-compose")) return 75;
        if (lower.startsWith("src/")) return 65;
        return 40;
    }

    private RepositoryRef parse(String sourceUrl) {
        if (sourceUrl == null || sourceUrl.isBlank()) return null;
        try {
            URI uri = URI.create(sourceUrl.trim());
            if (!List.of("http", "https").contains(uri.getScheme().toLowerCase(Locale.ROOT))) {
                return null;
            }
            String host = uri.getHost() == null ? "" : uri.getHost().toLowerCase(Locale.ROOT);
            String path = uri.getPath().replaceAll("^/+|/+$", "");
            if ("github.com".equals(host) || "www.github.com".equals(host)) {
                String[] parts = path.split("/");
                if (parts.length < 2) return null;
                return new RepositoryRef(
                        "GITHUB",
                        "https://github.com",
                        parts[0] + "/" + stripGit(parts[1])
                );
            }
            URI configuredGitLab = URI.create(stripTrailingSlash(properties.gitlab().baseUrl()));
            if (host.equalsIgnoreCase(configuredGitLab.getHost())) {
                int marker = path.indexOf("/-/");
                String fullName = marker >= 0 ? path.substring(0, marker) : path;
                if (!fullName.contains("/")) return null;
                return new RepositoryRef(
                        "GITLAB",
                        stripTrailingSlash(properties.gitlab().baseUrl()),
                        stripGit(fullName)
                );
            }
            return null;
        } catch (IllegalArgumentException exception) {
            return null;
        }
    }

    private void saveSnapshot(
            UUID userId,
            UUID evidenceId,
            UUID connectionId,
            RepositoryRef repository,
            Snapshot snapshot,
            JsonNode collected
    ) {
        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            insert into repository_evidence_snapshots (
                                user_id, evidence_id, connection_id, provider,
                                repository_full_name, commit_sha,
                                default_branch, collected_data
                            ) values (
                                :userId, :evidenceId, :connectionId, :provider,
                                :fullName, :commitSha,
                                :defaultBranch, cast(:collectedData as jsonb)
                            )
                            on conflict (evidence_id, commit_sha) do update set
                                connection_id = excluded.connection_id,
                                collected_data = excluded.collected_data,
                                collected_at = now()
                            """)
                    .param("userId", userId)
                    .param("evidenceId", evidenceId)
                    .param("connectionId", connectionId)
                    .param("provider", repository.provider())
                    .param("fullName", repository.fullName())
                    .param("commitSha", snapshot.commitSha())
                    .param("defaultBranch", snapshot.defaultBranch())
                    .param("collectedData", objectMapper.writeValueAsString(collected))
                    .update();
            return null;
        });
    }

    private static String encode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20");
    }

    private static String stripGit(String value) {
        return value.replaceFirst("(?i)\\.git$", "");
    }

    private static String stripTrailingSlash(String value) {
        return value == null ? "" : value.replaceAll("/+$", "");
    }

    private record RepositoryRef(String provider, String baseUrl, String fullName) {
    }

    private record TreeFile(String path, String sha, int priority) {
    }

    private record CapturedFile(String path, String content, boolean truncated) {
    }

    private record Snapshot(
            String commitSha,
            String defaultBranch,
            int treeItemCount,
            boolean treeTruncated,
            List<CapturedFile> files
    ) {
    }
}
