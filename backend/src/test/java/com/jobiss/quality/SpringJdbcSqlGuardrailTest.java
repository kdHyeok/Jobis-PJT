package com.jobiss.quality;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

class SpringJdbcSqlGuardrailTest {

    private static final Pattern JSONB_QUESTION_OPERATOR = Pattern.compile(
            "(?m)\\b[\\w.)]+\\s+\\?(?:\\||&)?\\s*'"
    );
    private static final Pattern NULL_PARAMETER_PREDICATE = Pattern.compile(
            "(?i):[a-z][a-z0-9_]*\\s+is\\s+(?:not\\s+)?null"
    );

    @Test
    void namedParameterSqlDoesNotContainAmbiguousPostgresPatterns()
            throws IOException {
        Path sourceRoot = Path.of("src", "main", "java");
        List<String> violations = new ArrayList<>();

        try (Stream<Path> files = Files.walk(sourceRoot)) {
            for (Path file : files.filter(path -> path.toString().endsWith(".java")).toList()) {
                String source = Files.readString(file, StandardCharsets.UTF_8);
                collectViolations(
                        file,
                        source,
                        JSONB_QUESTION_OPERATOR,
                        "PostgreSQL JSONB ? operator; use jsonb_exists*()"
                ).forEach(violations::add);
                collectViolations(
                        file,
                        source,
                        NULL_PARAMETER_PREDICATE,
                        "nullable named parameter predicate; branch SQL or pass a boolean"
                ).forEach(violations::add);
            }
        }

        assertThat(violations)
                .as("Spring named-parameter SQL guardrail violations")
                .isEmpty();
    }

    private List<String> collectViolations(
            Path file,
            String source,
            Pattern pattern,
            String explanation
    ) {
        List<String> violations = new ArrayList<>();
        Matcher matcher = pattern.matcher(source);
        while (matcher.find()) {
            long line = source.substring(0, matcher.start())
                    .chars()
                    .filter(character -> character == '\n')
                    .count() + 1;
            violations.add(
                    file + ":" + line + " — " + explanation
                            + " — `" + matcher.group().trim() + "`"
            );
        }
        return violations;
    }
}
