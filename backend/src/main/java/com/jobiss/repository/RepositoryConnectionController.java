package com.jobiss.repository;

import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/repository-connections")
public class RepositoryConnectionController {

    private final RepositoryConnectionService service;

    public RepositoryConnectionController(RepositoryConnectionService service) {
        this.service = service;
    }

    @GetMapping
    List<RepositoryConnectionService.ConnectionView> list(
            @AuthenticationPrincipal UUID userId
    ) {
        return service.list(userId);
    }

    @PostMapping("/{provider}/start")
    RepositoryConnectionService.StartView start(
            @AuthenticationPrincipal UUID userId,
            @PathVariable String provider
    ) {
        return service.start(userId, provider);
    }

    @PostMapping("/{provider}/complete")
    RepositoryConnectionService.ConnectionView complete(
            @AuthenticationPrincipal UUID userId,
            @PathVariable String provider,
            @Valid @RequestBody RepositoryConnectionService.CompleteRequest request
    ) {
        return service.complete(userId, provider, request);
    }

    @DeleteMapping("/{connectionId}")
    ResponseEntity<Void> disconnect(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID connectionId
    ) {
        service.disconnect(userId, connectionId);
        return ResponseEntity.noContent().build();
    }
}
