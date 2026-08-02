package com.jobiss.system;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.jdbc.core.simple.JdbcClient;

import java.time.Instant;
import java.util.Map;

@RestController
@RequestMapping("/api/health")
public class HealthController {

    private final JdbcClient jdbc;

    public HealthController(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping
    Map<String, Object> health() {
        Integer database = jdbc.sql("select 1").query(Integer.class).single();
        return Map.of(
                "status", "ok",
                "service", "jobiss-backend",
                "database", database == 1 ? "ok" : "unavailable",
                "timestamp", Instant.now()
        );
    }
}
