package com.jobiss.career;

import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequestMapping("/api/career-map")
public class CareerMapController {

    private final CareerMapService service;

    public CareerMapController(CareerMapService service) {
        this.service = service;
    }

    @GetMapping
    CareerMapService.CareerMap get(@AuthenticationPrincipal UUID userId) {
        return service.get(userId);
    }

    @PostMapping("/nodes/{nodeId}/self-confirm")
    ResponseEntity<Void> selfConfirm(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID nodeId
    ) {
        service.selfConfirm(userId, nodeId);
        return ResponseEntity.noContent().build();
    }
}
