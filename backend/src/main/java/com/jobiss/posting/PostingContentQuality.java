package com.jobiss.posting;

import com.jobiss.common.ApiException;
import org.springframework.http.HttpStatus;

import java.util.List;
import java.util.Locale;

final class PostingContentQuality {

    private static final int MINIMUM_USEFUL_LENGTH = 200;
    private static final List<String> RESPONSIBILITY_SIGNALS = List.of(
            "담당업무", "주요 업무", "주요업무", "하는 일", "업무 내용",
            "responsibilities", "what you'll do", "role description"
    );
    private static final List<String> REQUIREMENT_SIGNALS = List.of(
            "자격요건", "자격 요건", "지원자격", "지원 자격",
            "필수 요건", "필수요건", "요구사항",
            "requirements", "qualifications", "what we're looking for"
    );
    private static final List<String> PREFERENCE_SIGNALS = List.of(
            "우대사항", "우대 사항", "preferred", "nice to have", "우대 요건"
    );
    private static final List<String> EMPLOYMENT_SIGNALS = List.of(
            "채용", "모집", "고용형태", "고용 형태", "근무형태", "근무 형태", "경력", "신입",
            "employment", "career", "experience"
    );

    private PostingContentQuality() {
    }

    static void requireSufficient(String rawText) {
        String normalized = rawText == null
                ? ""
                : rawText.trim().replaceAll("\\s+", " ").toLowerCase(Locale.ROOT);
        int signalGroups = 0;
        boolean responsibilities = containsAny(normalized, RESPONSIBILITY_SIGNALS);
        boolean requirements = containsAny(normalized, REQUIREMENT_SIGNALS);
        if (responsibilities) signalGroups++;
        if (requirements) signalGroups++;
        if (containsAny(normalized, PREFERENCE_SIGNALS)) signalGroups++;
        if (containsAny(normalized, EMPLOYMENT_SIGNALS)) signalGroups++;

        if (normalized.length() < MINIMUM_USEFUL_LENGTH
                || signalGroups < 2
                || (!responsibilities && !requirements)) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_CONTENT,
                    "POSTING_SOURCE_INSUFFICIENT",
                    "공고의 담당 업무와 지원 조건을 충분히 가져오지 못했습니다. 채용 공고 원문을 직접 붙여 넣어 주세요."
            );
        }
    }

    private static boolean containsAny(String value, List<String> signals) {
        return signals.stream().anyMatch(value::contains);
    }
}
