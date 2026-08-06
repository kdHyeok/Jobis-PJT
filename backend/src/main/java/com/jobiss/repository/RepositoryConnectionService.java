package com.jobiss.repository;

import com.jobiss.common.ApiException;
import com.jobiss.config.RepositoryProperties;
import com.jobiss.db.RlsTransactionExecutor;
import io.jsonwebtoken.Jwts;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.SecureRandom;
import java.security.spec.PKCS8EncodedKeySpec;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.Date;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;

@Service
public class RepositoryConnectionService {

    private final RlsTransactionExecutor rls;
    private final RepositoryProperties properties;
    private final RepositoryTokenCipher tokenCipher;
    private final ObjectMapper objectMapper;
    private final RestClient http = RestClient.builder().build();
    private final SecureRandom random = new SecureRandom();

    public RepositoryConnectionService(
            RlsTransactionExecutor rls,
            RepositoryProperties properties,
            RepositoryTokenCipher tokenCipher,
            ObjectMapper objectMapper
    ) {
        this.rls = rls;
        this.properties = properties;
        this.tokenCipher = tokenCipher;
        this.objectMapper = objectMapper;
    }

    public List<ConnectionView> list(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            id, provider, provider_base_url,
                            external_account_name, status, scopes::text,
                            created_at, updated_at
                        from repository_connections
                        where status <> 'REVOKED'
                        order by provider
                        """)
                .query((rs, rowNum) -> new ConnectionView(
                        rs.getObject("id", UUID.class),
                        rs.getString("provider"),
                        rs.getString("provider_base_url"),
                        rs.getString("external_account_name"),
                        rs.getString("status"),
                        objectMapper.readTree(rs.getString("scopes")),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("updated_at", OffsetDateTime.class)
                ))
                .list());
    }

    public StartView start(UUID userId, String providerValue) {
        String provider = normalizeProvider(providerValue);
        byte[] stateBytes = new byte[32];
        random.nextBytes(stateBytes);
        String state = Base64.getUrlEncoder().withoutPadding().encodeToString(stateBytes);
        ProviderConfig config = providerConfig(provider);
        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            insert into repository_oauth_states (
                                user_id, provider, state_hash,
                                provider_base_url, redirect_uri, expires_at
                            ) values (
                                :userId, :provider, :stateHash,
                                :baseUrl, :redirectUri, now() + interval '10 minutes'
                            )
                            """)
                    .param("userId", userId)
                    .param("provider", provider)
                    .param("stateHash", sha256(state))
                    .param("baseUrl", config.baseUrl())
                    .param("redirectUri", config.redirectUri())
                    .update();
            return null;
        });
        String authorizationUrl = "GITHUB".equals(provider)
                ? githubInstallUrl(state)
                : gitlabAuthorizationUrl(config, state);
        return new StartView(provider, authorizationUrl, OffsetDateTime.now().plusMinutes(10));
    }

    public ConnectionView complete(
            UUID userId,
            String providerValue,
            CompleteRequest request
    ) {
        String provider = normalizeProvider(providerValue);
        OAuthState state = consumeState(userId, provider, request.state());
        ProviderIdentity identity = "GITHUB".equals(provider)
                ? completeGitHub(request.installationId())
                : completeGitLab(state, request.code());
        UUID connectionId = rls.write(userId, jdbc -> jdbc.sql("""
                        insert into repository_connections (
                            user_id, provider, provider_base_url,
                            external_account_id, external_account_name,
                            installation_id, encrypted_access_token,
                            encrypted_refresh_token, token_expires_at,
                            scopes, metadata, status
                        ) values (
                            :userId, :provider, :baseUrl,
                            :accountId, :accountName,
                            :installationId, :accessToken,
                            :refreshToken, :expiresAt,
                            cast(:scopes as jsonb), cast(:metadata as jsonb), 'ACTIVE'
                        )
                        on conflict (user_id, provider, provider_base_url)
                        do update set
                            external_account_id = excluded.external_account_id,
                            external_account_name = excluded.external_account_name,
                            installation_id = excluded.installation_id,
                            encrypted_access_token = excluded.encrypted_access_token,
                            encrypted_refresh_token = excluded.encrypted_refresh_token,
                            token_expires_at = excluded.token_expires_at,
                            scopes = excluded.scopes,
                            metadata = excluded.metadata,
                            status = 'ACTIVE',
                            updated_at = now()
                        returning id
                        """)
                .param("userId", userId)
                .param("provider", provider)
                .param("baseUrl", state.baseUrl())
                .param("accountId", identity.accountId())
                .param("accountName", identity.accountName())
                .param("installationId", identity.installationId())
                .param("accessToken", tokenCipher.encrypt(identity.accessToken()))
                .param("refreshToken", tokenCipher.encrypt(identity.refreshToken()))
                .param("expiresAt", identity.expiresAt())
                .param("scopes", objectMapper.writeValueAsString(identity.scopes()))
                .param("metadata", objectMapper.writeValueAsString(identity.metadata()))
                .query(UUID.class)
                .single());
        return list(userId).stream()
                .filter(item -> item.id().equals(connectionId))
                .findFirst()
                .orElseThrow();
    }

    public void disconnect(UUID userId, UUID connectionId) {
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update repository_connections
                            set
                                status = 'REVOKED',
                                encrypted_access_token = null,
                                encrypted_refresh_token = null,
                                updated_at = now()
                            where id = :connectionId
                            """)
                    .param("connectionId", connectionId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.NOT_FOUND,
                        "REPOSITORY_CONNECTION_NOT_FOUND",
                        "저장소 연결을 찾을 수 없습니다."
                );
            }
            return null;
        });
    }

    RepositoryAccess access(UUID userId, String provider, String baseUrl) {
        StoredConnection connection = rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            id, installation_id, encrypted_access_token,
                            encrypted_refresh_token, token_expires_at
                        from repository_connections
                        where provider = :provider
                          and provider_base_url = :baseUrl
                          and status = 'ACTIVE'
                        """)
                .param("provider", provider)
                .param("baseUrl", baseUrl)
                .query((rs, rowNum) -> new StoredConnection(
                        rs.getObject("id", UUID.class),
                        rs.getString("installation_id"),
                        rs.getString("encrypted_access_token"),
                        rs.getString("encrypted_refresh_token"),
                        rs.getObject("token_expires_at", OffsetDateTime.class)
                ))
                .optional()
                .orElse(null));
        if (connection == null) return new RepositoryAccess(null, null);
        if ("GITHUB".equals(provider)) {
            return new RepositoryAccess(
                    connection.id(),
                    githubInstallationToken(connection.installationId())
            );
        }
        if (connection.tokenExpiresAt() != null
                && connection.tokenExpiresAt().isBefore(OffsetDateTime.now().plusMinutes(2))
                && connection.encryptedRefreshToken() != null) {
            return refreshGitLabAccess(userId, connection, baseUrl);
        }
        return new RepositoryAccess(
                connection.id(),
                tokenCipher.decrypt(connection.encryptedAccessToken())
        );
    }

    private RepositoryAccess refreshGitLabAccess(
            UUID userId,
            StoredConnection connection,
            String baseUrl
    ) {
        String refreshToken = tokenCipher.decrypt(connection.encryptedRefreshToken());
        LinkedMultiValueMap<String, String> form = new LinkedMultiValueMap<>();
        form.add("client_id", properties.gitlab().clientId());
        form.add("client_secret", properties.gitlab().clientSecret());
        form.add("refresh_token", refreshToken);
        form.add("grant_type", "refresh_token");
        JsonNode token = http.post()
                .uri(baseUrl + "/oauth/token")
                .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                .body(form)
                .retrieve()
                .body(JsonNode.class);
        String accessToken = token.path("access_token").stringValue("");
        if (accessToken.isBlank()) {
            markReauthenticationRequired(userId, connection.id());
            throw providerFailure("GitLab 연결을 다시 인증해 주세요.");
        }
        String rotatedRefresh = token.path("refresh_token").stringValue(refreshToken);
        OffsetDateTime expiresAt = OffsetDateTime.now()
                .plusSeconds(token.path("expires_in").longValue(7200));
        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            update repository_connections
                            set
                                encrypted_access_token = :accessToken,
                                encrypted_refresh_token = :refreshToken,
                                token_expires_at = :expiresAt,
                                updated_at = now()
                            where id = :connectionId
                            """)
                    .param("accessToken", tokenCipher.encrypt(accessToken))
                    .param("refreshToken", tokenCipher.encrypt(rotatedRefresh))
                    .param("expiresAt", expiresAt)
                    .param("connectionId", connection.id())
                    .update();
            return null;
        });
        return new RepositoryAccess(connection.id(), accessToken);
    }

    private void markReauthenticationRequired(UUID userId, UUID connectionId) {
        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            update repository_connections
                            set status = 'REAUTH_REQUIRED', updated_at = now()
                            where id = :connectionId
                            """)
                    .param("connectionId", connectionId)
                    .update();
            return null;
        });
    }

    private OAuthState consumeState(UUID userId, String provider, String rawState) {
        if (rawState == null || rawState.isBlank()) throw invalidCallback();
        return rls.write(userId, jdbc -> jdbc.sql("""
                        update repository_oauth_states
                        set consumed_at = now()
                        where provider = :provider
                          and state_hash = :stateHash
                          and consumed_at is null
                          and expires_at > now()
                        returning provider_base_url, redirect_uri
                        """)
                .param("provider", provider)
                .param("stateHash", sha256(rawState))
                .query((rs, rowNum) -> new OAuthState(
                        rs.getString("provider_base_url"),
                        rs.getString("redirect_uri")
                ))
                .optional()
                .orElseThrow(RepositoryConnectionService::invalidCallback));
    }

    private ProviderIdentity completeGitHub(String installationId) {
        if (installationId == null || !installationId.matches("^[0-9]{1,30}$")) {
            throw invalidCallback();
        }
        JsonNode installation = githubRequest(
                "/app/installations/" + installationId,
                githubAppJwt()
        );
        JsonNode account = installation.path("account");
        return new ProviderIdentity(
                account.path("id").stringValue(),
                account.path("login").stringValue("GitHub account"),
                installationId,
                null,
                null,
                null,
                objectMapper.valueToTree(List.of("contents:read", "metadata:read")),
                objectMapper.valueToTree(java.util.Map.of(
                        "targetType", installation.path("target_type").stringValue("Account")
                ))
        );
    }

    private ProviderIdentity completeGitLab(OAuthState state, String code) {
        RepositoryProperties.GitLab gitlab = properties.gitlab();
        if (code == null || code.isBlank()) throw invalidCallback();
        LinkedMultiValueMap<String, String> form = new LinkedMultiValueMap<>();
        form.add("client_id", gitlab.clientId());
        form.add("client_secret", gitlab.clientSecret());
        form.add("code", code);
        form.add("grant_type", "authorization_code");
        form.add("redirect_uri", state.redirectUri());
        JsonNode token = http.post()
                .uri(state.baseUrl() + "/oauth/token")
                .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                .body(form)
                .retrieve()
                .body(JsonNode.class);
        String accessToken = token.path("access_token").stringValue("");
        if (accessToken.isBlank()) throw providerFailure("GitLab 토큰을 받지 못했습니다.");
        JsonNode user = http.get()
                .uri(state.baseUrl() + "/api/v4/user")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + accessToken)
                .retrieve()
                .body(JsonNode.class);
        long expiresIn = token.path("expires_in").asLong(7200);
        return new ProviderIdentity(
                user.path("id").stringValue(),
                user.path("username").stringValue("GitLab account"),
                null,
                accessToken,
                token.path("refresh_token").stringValue(null),
                OffsetDateTime.now().plusSeconds(expiresIn),
                objectMapper.valueToTree(List.of("read_api", "read_repository")),
                objectMapper.createObjectNode()
        );
    }

    private String githubInstallationToken(String installationId) {
        if (installationId == null || installationId.isBlank()) {
            throw providerFailure("GitHub App 설치 정보가 없습니다.");
        }
        JsonNode response = http.post()
                .uri(properties.github().apiBaseUrl()
                        + "/app/installations/" + installationId + "/access_tokens")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + githubAppJwt())
                .header(HttpHeaders.ACCEPT, "application/vnd.github+json")
                .retrieve()
                .body(JsonNode.class);
        String token = response.path("token").stringValue("");
        if (token.isBlank()) throw providerFailure("GitHub 설치 토큰을 받지 못했습니다.");
        return token;
    }

    private JsonNode githubRequest(String path, String jwt) {
        return http.get()
                .uri(properties.github().apiBaseUrl() + path)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + jwt)
                .header(HttpHeaders.ACCEPT, "application/vnd.github+json")
                .retrieve()
                .body(JsonNode.class);
    }

    private String githubAppJwt() {
        RepositoryProperties.GitHub github = properties.github();
        if (blank(github.appId()) || blank(github.privateKey())) {
            throw providerFailure("GitHub App ID와 PKCS#8 개인 키가 설정되지 않았습니다.");
        }
        Instant now = Instant.now();
        return Jwts.builder()
                .issuer(github.appId())
                .issuedAt(Date.from(now.minusSeconds(60)))
                .expiration(Date.from(now.plusSeconds(9 * 60)))
                .signWith(readPrivateKey(github.privateKey()), Jwts.SIG.RS256)
                .compact();
    }

    private PrivateKey readPrivateKey(String configured) {
        try {
            String pem = configured.replace("\\n", "\n").trim();
            String normalized = pem
                    .replace("-----BEGIN PRIVATE KEY-----", "")
                    .replace("-----END PRIVATE KEY-----", "")
                    .replaceAll("\\s", "");
            byte[] key = Base64.getDecoder().decode(normalized);
            return KeyFactory.getInstance("RSA")
                    .generatePrivate(new PKCS8EncodedKeySpec(key));
        } catch (Exception exception) {
            throw providerFailure("GitHub App 개인 키는 PKCS#8 PEM 형식이어야 합니다.");
        }
    }

    private String githubInstallUrl(String state) {
        String slug = properties.github().appSlug();
        if (blank(slug)) throw providerFailure("GITHUB_APP_SLUG가 설정되지 않았습니다.");
        return "https://github.com/apps/" + encode(slug)
                + "/installations/new?state=" + encode(state);
    }

    private String gitlabAuthorizationUrl(ProviderConfig config, String state) {
        RepositoryProperties.GitLab gitlab = properties.gitlab();
        if (blank(gitlab.clientId()) || blank(gitlab.clientSecret())) {
            throw providerFailure("GitLab OAuth 애플리케이션 설정이 없습니다.");
        }
        return config.baseUrl() + "/oauth/authorize?client_id=" + encode(gitlab.clientId())
                + "&redirect_uri=" + encode(config.redirectUri())
                + "&response_type=code&scope=" + encode("read_api read_repository")
                + "&state=" + encode(state);
    }

    private ProviderConfig providerConfig(String provider) {
        if ("GITHUB".equals(provider)) {
            return new ProviderConfig("https://github.com", properties.github().redirectUri());
        }
        return new ProviderConfig(
                stripTrailingSlash(properties.gitlab().baseUrl()),
                properties.gitlab().redirectUri()
        );
    }

    private String normalizeProvider(String value) {
        String provider = value == null ? "" : value.trim().toUpperCase();
        if (!List.of("GITHUB", "GITLAB").contains(provider)) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "UNSUPPORTED_REPOSITORY_PROVIDER",
                    "GitHub 또는 GitLab만 연결할 수 있습니다."
            );
        }
        return provider;
    }

    private String sha256(String value) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256")
                            .digest(value.getBytes(StandardCharsets.UTF_8))
            );
        } catch (Exception exception) {
            throw new IllegalStateException(exception);
        }
    }

    private static String encode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    private static String stripTrailingSlash(String value) {
        return value == null ? "" : value.replaceAll("/+$", "");
    }

    private static boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private static ApiException invalidCallback() {
        return new ApiException(
                HttpStatus.BAD_REQUEST,
                "INVALID_REPOSITORY_CALLBACK",
                "저장소 연결 요청이 만료되었거나 올바르지 않습니다."
        );
    }

    private static ApiException providerFailure(String message) {
        return new ApiException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "REPOSITORY_PROVIDER_UNAVAILABLE",
                message
        );
    }

    public record StartView(
            String provider,
            String authorizationUrl,
            OffsetDateTime expiresAt
    ) {
    }

    public record CompleteRequest(
            String state,
            String code,
            String installationId
    ) {
    }

    public record ConnectionView(
            UUID id,
            String provider,
            String providerBaseUrl,
            String accountName,
            String status,
            JsonNode scopes,
            OffsetDateTime createdAt,
            OffsetDateTime updatedAt
    ) {
    }

    record RepositoryAccess(UUID connectionId, String token) {
    }

    private record ProviderConfig(String baseUrl, String redirectUri) {
    }

    private record OAuthState(String baseUrl, String redirectUri) {
    }

    private record StoredConnection(
            UUID id,
            String installationId,
            String encryptedAccessToken,
            String encryptedRefreshToken,
            OffsetDateTime tokenExpiresAt
    ) {
    }

    private record ProviderIdentity(
            String accountId,
            String accountName,
            String installationId,
            String accessToken,
            String refreshToken,
            OffsetDateTime expiresAt,
            JsonNode scopes,
            JsonNode metadata
    ) {
    }
}
