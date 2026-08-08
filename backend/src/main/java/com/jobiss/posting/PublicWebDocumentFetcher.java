package com.jobiss.posting;

import com.jobiss.common.ApiException;
import com.jobiss.common.WebUrls;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.util.HtmlUtils;

import java.io.InputStream;
import java.net.InetAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Arrays;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Component
public class PublicWebDocumentFetcher {

    private static final int MAX_BYTES = 2_000_000;
    private static final Pattern CHARSET = Pattern.compile("charset=([^;\\s]+)", Pattern.CASE_INSENSITIVE);
    private static final Pattern META_CHARSET = Pattern.compile(
            "(?i)<meta[^>]+charset=[\\\"']?([^\\\"'\\s/>]+)"
    );
    private final HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(8))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    public void validatePublicUrl(String sourceUrl) {
        try {
            validatePublicAddress(URI.create(sourceUrl.trim()));
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw invalid("올바른 http 또는 https 공고 URL을 입력해 주세요.");
        }
    }

    public FetchedDocument fetch(String sourceUrl) {
        URI current = URI.create(sourceUrl.trim());
        for (int redirects = 0; redirects <= 3; redirects++) {
            validatePublicAddress(current);
            HttpRequest request = HttpRequest.newBuilder(current)
                    .timeout(Duration.ofSeconds(15))
                    .header("User-Agent", "JOBIS/1.0 posting-import")
                    .header("Accept", "text/html,text/plain;q=0.9")
                    .GET()
                    .build();
            try {
                HttpResponse<InputStream> response = client.send(
                        request,
                        HttpResponse.BodyHandlers.ofInputStream()
                );
                if (response.statusCode() >= 300 && response.statusCode() < 400) {
                    String location = response.headers().firstValue("location").orElseThrow(
                            () -> invalid("공고 URL의 이동 주소를 확인할 수 없습니다.")
                    );
                    current = current.resolve(location);
                    continue;
                }
                if (response.statusCode() < 200 || response.statusCode() >= 300) {
                    throw invalid("공고 페이지가 HTTP " + response.statusCode() + " 응답을 반환했습니다.");
                }
                String contentType = response.headers().firstValue("content-type")
                        .orElse("text/html").toLowerCase(Locale.ROOT);
                if (!contentType.startsWith("text/html") && !contentType.startsWith("text/plain")) {
                    throw invalid("HTML 또는 텍스트 공고만 가져올 수 있습니다.");
                }
                byte[] body;
                try (InputStream responseBody = response.body()) {
                    body = responseBody.readNBytes(MAX_BYTES + 1);
                }
                if (body.length > MAX_BYTES) {
                    throw invalid("공고 페이지가 너무 커서 자동으로 가져올 수 없습니다.");
                }
                Charset charset = charset(contentType, body);
                String decoded = new String(body, charset);
                String text = contentType.startsWith("text/plain") ? decoded : htmlToText(decoded);
                PostingContentQuality.requireSufficient(text);
                return new FetchedDocument(current.toString(), text.substring(0, Math.min(text.length(), 100_000)));
            } catch (ApiException exception) {
                throw exception;
            } catch (Exception exception) {
                throw invalid("공고 페이지를 가져오지 못했습니다. 원문을 직접 붙여넣어 주세요.");
            }
        }
        throw invalid("공고 URL의 이동 횟수가 너무 많습니다.");
    }

    private void validatePublicAddress(URI uri) {
        if (!WebUrls.isHttpUrl(uri.toString())) throw invalid("http 또는 https 공고 URL을 입력해 주세요.");
        try {
            boolean unsafe = Arrays.stream(InetAddress.getAllByName(uri.getHost()))
                    .anyMatch(address -> address.isAnyLocalAddress()
                            || address.isLoopbackAddress()
                            || address.isLinkLocalAddress()
                            || address.isSiteLocalAddress()
                            || address.isMulticastAddress()
                            || isUniqueLocalIpv6(address.getAddress()));
            if (unsafe) throw invalid("내부 네트워크 주소는 가져올 수 없습니다.");
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw invalid("공고 URL의 호스트를 확인하지 못했습니다.");
        }
    }

    private boolean isUniqueLocalIpv6(byte[] bytes) {
        return bytes.length == 16 && (bytes[0] & 0xfe) == 0xfc;
    }

    private Charset charset(String contentType, byte[] body) {
        Matcher headerMatcher = CHARSET.matcher(contentType);
        if (headerMatcher.find()) {
            return parseCharset(headerMatcher.group(1));
        }
        String prefix = new String(
                body,
                0,
                Math.min(body.length, 8_192),
                StandardCharsets.ISO_8859_1
        );
        Matcher metaMatcher = META_CHARSET.matcher(prefix);
        if (metaMatcher.find()) {
            return parseCharset(metaMatcher.group(1));
        }
        return StandardCharsets.UTF_8;
    }

    private Charset parseCharset(String value) {
        try {
            return Charset.forName(value.replace("\"", "").replace("'", ""));
        } catch (Exception ignored) {
            return StandardCharsets.UTF_8;
        }
    }

    private String htmlToText(String html) {
        String cleaned = html
                .replaceAll("(?is)<(script|style|noscript|svg)[^>]*>.*?</\\1>", " ")
                .replaceAll("(?i)<br\\s*/?>", "\n")
                .replaceAll("(?i)</(p|div|li|section|article|h[1-6]|tr)>", "\n")
                .replaceAll("(?is)<[^>]+>", " ");
        String unescaped = HtmlUtils.htmlUnescape(cleaned).replace('\u00a0', ' ');
        return unescaped.lines()
                .map(line -> line.trim().replaceAll("[\\t ]+", " "))
                .filter(line -> !line.isBlank())
                .reduce((left, right) -> left + "\n" + right)
                .orElse("");
    }

    private ApiException invalid(String message) {
        return new ApiException(HttpStatus.UNPROCESSABLE_CONTENT, "POSTING_URL_IMPORT_FAILED", message);
    }

    public record FetchedDocument(String finalUrl, String rawText) {}
}
