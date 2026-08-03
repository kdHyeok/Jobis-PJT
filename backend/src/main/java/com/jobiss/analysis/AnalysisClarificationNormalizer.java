package com.jobiss.analysis;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Keeps AI-generated clarification vocabulary out of cache identities.
 * The model may say "junior" on one run and "entry" on another; those
 * answers still describe the same analysis context and must share a cache key.
 */
public final class AnalysisClarificationNormalizer {

    private AnalysisClarificationNormalizer() {
    }

    public static AiContracts.AnalysisQuestion normalize(
            AiContracts.AnalysisQuestion question
    ) {
        String key = questionKey(question.key());
        List<AiContracts.AnalysisQuestionOption> options = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (AiContracts.AnalysisQuestionOption option : question.options()) {
            String value = answerValue(key, option.value(), option.label());
            if (seen.add(value)) {
                options.add(new AiContracts.AnalysisQuestionOption(
                        value,
                        option.label(),
                        option.description()
                ));
            }
        }
        if (options.size() < 2) {
            throw new IllegalStateException(
                    "AI clarification options collapse to fewer than two meanings"
            );
        }
        return new AiContracts.AnalysisQuestion(
                key,
                question.text(),
                question.reason(),
                options
        );
    }

    public static AiContracts.AnalysisAnswer normalize(
            AiContracts.AnalysisAnswer answer
    ) {
        String key = questionKey(answer.questionKey());
        return new AiContracts.AnalysisAnswer(
                key,
                answer.questionText(),
                answerValue(key, answer.answerValue(), answer.answerLabel()),
                answer.answerLabel()
        );
    }

    public static String questionKey(String rawKey) {
        String key = token(rawKey);
        if (key.contains("track") || key.contains("role") || key.contains("position")) {
            return "target_track";
        }
        if (key.contains("career")
                || key.contains("experience")
                || key.contains("seniority")
                || key.contains("level")) {
            return "career_stage";
        }
        return key.isBlank() ? "clarification" : limit(key, 80);
    }

    public static String answerValue(
            String normalizedQuestionKey,
            String rawValue,
            String rawLabel
    ) {
        String combined = token(rawValue) + " " + token(rawLabel);
        if ("target_track".equals(normalizedQuestionKey)) {
            return normalizeTrack(combined, rawValue);
        }
        if ("career_stage".equals(normalizedQuestionKey)) {
            return normalizeCareerStage(combined, rawValue);
        }
        String fallback = token(rawValue);
        return limit(fallback.isBlank() ? "selected" : fallback, 120);
    }

    public static String fingerprint(List<AiContracts.AnalysisAnswer> answers) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            List<String> normalized = answers.stream()
                    .map(AnalysisClarificationNormalizer::normalize)
                    .map(answer -> answer.questionKey() + "=" + answer.answerValue())
                    .distinct()
                    .sorted()
                    .toList();
            return HexFormat.of().formatHex(
                    digest.digest(
                            String.join("|", normalized)
                                    .getBytes(StandardCharsets.UTF_8)
                    )
            );
        } catch (Exception exception) {
            throw new IllegalStateException(
                    "Could not fingerprint analysis clarifications",
                    exception
            );
        }
    }

    private static String normalizeTrack(String value, String fallback) {
        if (containsAny(value, "backend", "back_end", "server", "백엔드")) {
            return "backend";
        }
        if (containsAny(value, "frontend", "front_end", "프론트엔드")) {
            return "frontend";
        }
        if (containsAny(value, "fullstack", "full_stack", "풀스택")) {
            return "fullstack";
        }
        if (containsAny(value, "devops", "데브옵스")) {
            return "devops";
        }
        if (containsAny(value, "cloud", "클라우드")) {
            return "cloud";
        }
        if (containsAny(value, "security", "보안")) {
            return "security";
        }
        if (containsAny(value, "mobile", "android", "ios", "모바일")) {
            return "mobile";
        }
        if (containsAny(value, "game", "게임")) {
            return "game";
        }
        if (containsAny(value, "machine_learning", "artificial_intelligence", " ai ", "인공지능")) {
            return "ai";
        }
        if (containsAny(value, "data", "데이터")) {
            return "data";
        }
        return limit(token(fallback), 120);
    }

    private static String normalizeCareerStage(String value, String fallback) {
        if (containsAny(
                value,
                "entry",
                "junior",
                "new_grad",
                "newcomer",
                "fresher",
                "신입"
        )) {
            return "entry";
        }
        if (containsAny(
                value,
                "irrelevant",
                "no_experience_requirement",
                "experience_not_required",
                "경력무관",
                "경력_무관"
        )) {
            return "experience_irrelevant";
        }
        if (containsAny(value, "experienced", "senior", "career", "경력")) {
            return "experienced";
        }
        return limit(token(fallback), 120);
    }

    private static boolean containsAny(String value, String... candidates) {
        for (String candidate : candidates) {
            if (value.contains(candidate)) {
                return true;
            }
        }
        return false;
    }

    private static String token(String value) {
        if (value == null) {
            return "";
        }
        String normalized = Normalizer.normalize(value, Normalizer.Form.NFKC)
                .trim()
                .toLowerCase(Locale.ROOT);
        return normalized
                .replaceAll("[^\\p{L}\\p{N}._-]+", "_")
                .replaceAll("_+", "_")
                .replaceAll("^[_.-]+|[_.-]+$", "");
    }

    private static String limit(String value, int maximum) {
        return value.length() <= maximum ? value : value.substring(0, maximum);
    }
}
