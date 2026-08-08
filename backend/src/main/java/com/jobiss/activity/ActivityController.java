package com.jobiss.activity;

import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/activity")
public class ActivityController {

    private final ActivityJobService service;

    public ActivityController(ActivityJobService service) {
        this.service = service;
    }

    @GetMapping("/jobs")
    List<ActivityJobService.ActivityJobView> jobs(@AuthenticationPrincipal UUID userId) {
        return service.active(userId);
    }
}
