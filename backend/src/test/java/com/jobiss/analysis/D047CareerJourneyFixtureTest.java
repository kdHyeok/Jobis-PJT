package com.jobiss.analysis;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

class D047CareerJourneyFixtureTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void preservesCareerGateAndSecuritySectionAcrossTheServiceBoundary() throws Exception {
        Path fixturePath = Path.of(
                "..",
                "contract-fixtures",
                "d047",
                "career-journey-acceptance.json"
        ).normalize();
        JsonNode fixture = objectMapper.readTree(Files.readString(fixturePath));

        JsonNode backendJourney = fixture.path("scenarios").path("entryToExperiencedBackend");
        JsonNode gate = backendJourney.path("expectedJourney").path("experienceGate");
        assertEquals(24, gate.path("minimumMonths").asInt());
        assertEquals(48, gate.path("maximumMonths").asInt());
        assertTrue(gate.path("evidenceRequired").asBoolean());

        JsonNode securityJourney = fixture.path("scenarios").path("experiencedSecurity");
        assertEquals("SECURITY_ENGINEERING", securityJourney.path("posting").path("roleFamily").asText());
        assertEquals(
                "section.security_engineering",
                securityJourney.path("expectedJourney").path("sectionKey").asText()
        );
    }
}
