package com.jobiss.profile;

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
@RequestMapping("/api/profile/goals")
public class GoalProfileController {

    private final GoalProfileService service;

    public GoalProfileController(GoalProfileService service) {
        this.service = service;
    }

    @GetMapping
    GoalProfileService.GoalProfileView get(
            @AuthenticationPrincipal UUID userId
    ) {
        return service.get(userId);
    }

    @PutMapping
    GoalProfileService.GoalProfileView update(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody UpdateGoalProfileRequest request
    ) {
        return service.update(
                userId,
                request.currentGoalPostingId(),
                request.finalGoalText()
        );
    }

    record UpdateGoalProfileRequest(
            UUID currentGoalPostingId,
            @Size(max = 2000) String finalGoalText
    ) {
    }
}
