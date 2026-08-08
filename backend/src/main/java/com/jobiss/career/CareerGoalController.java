package com.jobiss.career;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Size;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequestMapping("/api/career-goals")
public class CareerGoalController {

    private final CareerGoalService service;

    public CareerGoalController(CareerGoalService service) {
        this.service = service;
    }

    @GetMapping
    CareerGoalService.CareerGoals get(@AuthenticationPrincipal UUID userId) {
        return service.get(userId);
    }

    @PutMapping
    CareerGoalService.CareerGoals update(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody UpdateRequest request
    ) {
        return service.update(userId, new CareerGoalService.UpdateCareerGoals(
                request.currentPostingId(),
                request.finalPostingId(),
                request.finalGoalText()
        ));
    }

    record UpdateRequest(
            UUID currentPostingId,
            UUID finalPostingId,
            @Size(max = 240) String finalGoalText
    ) {
    }
}
