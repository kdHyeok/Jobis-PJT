package com.jobiss.conversation;

import com.jobiss.analysis.v3.V3SourceService;
import org.junit.jupiter.api.Test;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

class ChatReplyJobServiceIntentTest {

    @Test
    void acceptsKoreanRoadmapBuildIntent() {
        assertThat(ChatReplyJobService.containsExplicitAnalysisIntent(
                "이 공고 기준으로 준비 로드맵을 세워줘"
        )).isTrue();
        assertThat(ChatReplyJobService.containsExplicitAnalysisIntent(
                "이 공고로 취업 로드맵 짜 줘"
        )).isTrue();
    }

    @Test
    void roadmapReadRequestDoesNotStartAnalysis() {
        assertThat(ChatReplyJobService.containsExplicitAnalysisIntent(
                "현재 로드맵 보여줘"
        )).isFalse();
    }

    @Test
    void urlActionPreservesUrlSourceAndSpaFragment() {
        UUID postingId = UUID.randomUUID();
        String url = "https://hanwhaaerospace-recruit.com/jdebook/#2@01-02@new";
        var action = new ChatAgentActionValidator.PostingAnalysisAction(
                postingId, "URL", url, "수집된 원문", "검토 본문"
        );

        V3SourceService.AcquireCommand command =
                ChatReplyJobService.sourceAcquireCommand(action);

        assertThat(command.inputType()).isEqualTo("URL");
        assertThat(command.postingId()).isEqualTo(postingId);
        assertThat(command.url()).isEqualTo(url);
        assertThat(command.text()).isNull();
    }

    @Test
    void textActionKeepsTextPayload() {
        var action = new ChatAgentActionValidator.PostingAnalysisAction(
                null, "TEXT", null, "회사명 직무명 필수 요건", "검토 본문"
        );

        V3SourceService.AcquireCommand command =
                ChatReplyJobService.sourceAcquireCommand(action);

        assertThat(command.inputType()).isEqualTo("TEXT");
        assertThat(command.text()).isEqualTo("회사명 직무명 필수 요건");
        assertThat(command.url()).isNull();
    }
}
