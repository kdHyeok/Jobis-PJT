package com.jobiss.posting;

import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.analysis.AiContracts;
import com.jobiss.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientException;

import java.util.List;

@Service
public class AgentPostingUrlImportService {

    private final AiAnalysisClient aiClient;
    private final PublicWebDocumentFetcher publicUrlValidator;

    public AgentPostingUrlImportService(
            AiAnalysisClient aiClient,
            PublicWebDocumentFetcher publicUrlValidator
    ) {
        this.aiClient = aiClient;
        this.publicUrlValidator = publicUrlValidator;
    }

    public ImportedPosting importUrl(String sourceUrl) {
        String normalizedUrl = sourceUrl.trim();
        publicUrlValidator.validatePublicUrl(normalizedUrl);

        AiContracts.PostingImportResponse response;
        try {
            response = aiClient.importPosting(new AiContracts.PostingImportRequest(normalizedUrl));
        } catch (RestClientException exception) {
            throw new ApiException(
                    HttpStatus.SERVICE_UNAVAILABLE,
                    "POSTING_IMPORT_AGENT_UNAVAILABLE",
                    "공고 수집 에이전트에 연결하지 못했습니다. 잠시 후 다시 시도하거나 원문을 직접 붙여넣어 주세요."
            );
        }

        String rawText = response == null || response.rawText() == null
                ? ""
                : response.rawText().trim();
        PostingContentQuality.requireSufficient(rawText);

        String finalUrl = response.finalUrl() == null || response.finalUrl().isBlank()
                ? normalizedUrl
                : response.finalUrl().trim();
        if (!finalUrl.equals(normalizedUrl)) {
            publicUrlValidator.validatePublicUrl(finalUrl);
        }

        List<ImportWarning> warnings = response.warnings() == null
                ? List.of()
                : response.warnings().stream()
                .filter(warning -> warning != null && warning.code() != null && warning.message() != null)
                .map(warning -> new ImportWarning(warning.code(), warning.message()))
                .toList();
        return new ImportedPosting(finalUrl, rawText, warnings, "AGENT");
    }

    public record ImportWarning(String code, String message) {
    }

    public record ImportedPosting(
            String finalUrl,
            String rawText,
            List<ImportWarning> warnings,
            String collector
    ) {
    }
}
