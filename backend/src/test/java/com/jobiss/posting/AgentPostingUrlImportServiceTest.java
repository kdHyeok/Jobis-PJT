package com.jobiss.posting;

import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.analysis.AiContracts;
import com.jobiss.analysis.AiServiceException;
import com.jobiss.common.ApiException;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AgentPostingUrlImportServiceTest {

    private final AiAnalysisClient aiClient = mock(AiAnalysisClient.class);
    private final PublicWebDocumentFetcher urlValidator = mock(PublicWebDocumentFetcher.class);
    private final AgentPostingUrlImportService service = new AgentPostingUrlImportService(
            aiClient,
            urlValidator
    );

    @Test
    void importsThroughAiAdapterAndPreservesWarnings() {
        String url = "https://example.com/jobs/1";
        String rawText = ("Responsibilities: build backend services. "
                + "Requirements: Java and Spring experience. ").repeat(5);
        when(aiClient.importPosting(new AiContracts.PostingImportRequest(url)))
                .thenReturn(new AiContracts.PostingImportResponse(
                        url,
                        rawText,
                        List.of(new AiContracts.PostingImportWarning(
                                "iframe_empty",
                                "상세 영역이 비어 있습니다."
                        ))
                ));

        AgentPostingUrlImportService.ImportedPosting imported = service.importUrl("  " + url + "  ");

        assertEquals(url, imported.finalUrl());
        assertEquals(rawText.trim(), imported.rawText());
        assertEquals("AGENT", imported.collector());
        assertEquals("iframe_empty", imported.warnings().get(0).code());
        verify(urlValidator).validatePublicUrl(url);
    }

    @Test
    void rejectsThinAgentResult() {
        String url = "https://example.com/jobs/1";
        when(aiClient.importPosting(new AiContracts.PostingImportRequest(url)))
                .thenReturn(new AiContracts.PostingImportResponse(url, "로그인 해주세요", List.of()));

        ApiException exception = assertThrows(ApiException.class, () -> service.importUrl(url));

        assertEquals("POSTING_SOURCE_INSUFFICIENT", exception.code());
    }

    @Test
    void exposesStableErrorWhenAgentIsUnavailable() {
        String url = "https://example.com/jobs/1";
        when(aiClient.importPosting(new AiContracts.PostingImportRequest(url)))
                .thenThrow(new AiServiceException("AI_PROVIDER_UNAVAILABLE", "upstream failed"));

        ApiException exception = assertThrows(ApiException.class, () -> service.importUrl(url));

        assertEquals("POSTING_IMPORT_AGENT_UNAVAILABLE", exception.code());
    }
}
