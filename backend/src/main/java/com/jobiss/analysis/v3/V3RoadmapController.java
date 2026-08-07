package com.jobiss.analysis.v3;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;
import java.util.List;

@RestController
@RequestMapping("/api/v3/roadmap")
public class V3RoadmapController {

    private final V3RoadmapService service;
    private final V3ProjectTaskProgressService taskProgressService;

    public V3RoadmapController(
            V3RoadmapService service,
            V3ProjectTaskProgressService taskProgressService
    ) {
        this.service = service;
        this.taskProgressService = taskProgressService;
    }

    @GetMapping
    V3RoadmapService.Workspace get(@AuthenticationPrincipal UUID userId) {
        return service.get(userId);
    }

    @GetMapping("/proposals/{proposalId}")
    V3RoadmapService.ProposalView proposal(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID proposalId
    ) {
        return service.proposal(userId, proposalId);
    }

    @PostMapping("/proposals/{proposalId}/preview")
    V3RoadmapService.PreviewResult preview(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID proposalId
    ) {
        return service.preview(userId, proposalId);
    }

    @PostMapping("/proposals/{proposalId}/apply")
    V3RoadmapService.ApplyResult apply(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID proposalId,
            @Valid @RequestBody ApplyRequest request
    ) {
        return service.apply(userId, proposalId, request.expectedRoadmapVersion());
    }

    @PostMapping("/proposals/{proposalId}/cancel")
    V3RoadmapService.CancelResult cancel(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID proposalId
    ) {
        return service.cancel(userId, proposalId);
    }

    @PostMapping("/targets/{postingId}/remove-draft")
    V3RoadmapService.ProposalView removeTargetDraft(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID postingId
    ) {
        return service.createTargetRemovalDraft(userId, postingId.toString());
    }

    @PostMapping("/reset-draft")
    V3RoadmapService.ProposalView resetDraft(@AuthenticationPrincipal UUID userId) {
        return service.createResetDraft(userId);
    }

    @GetMapping("/versions")
    List<V3RoadmapService.VersionView> versions(@AuthenticationPrincipal UUID userId) {
        return service.versions(userId);
    }

    @PostMapping("/versions/{versionId}/restore")
    V3RoadmapService.ApplyResult restore(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID versionId
    ) {
        return service.restoreVersion(userId, versionId);
    }

    @GetMapping("/projects/{projectNodeId}/tasks")
    List<V3ProjectTaskProgressService.TaskView> projectTasks(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID projectNodeId
    ) {
        return taskProgressService.tasks(userId, projectNodeId);
    }

    @PostMapping("/projects/{projectNodeId}/tasks/{taskKey}/state")
    V3ProjectTaskProgressService.TaskView updateProjectTaskState(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID projectNodeId,
            @PathVariable String taskKey,
            @Valid @RequestBody TaskStateRequest request
    ) {
        return taskProgressService.updateState(userId, projectNodeId, taskKey, request.state());
    }

    @PostMapping("/projects/{projectNodeId}/tasks/{taskKey}/evidence")
    V3ProjectTaskProgressService.TaskView addProjectTaskEvidence(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID projectNodeId,
            @PathVariable String taskKey,
            @Valid @RequestBody TaskEvidenceRequest request
    ) {
        return taskProgressService.addEvidence(
                userId, projectNodeId, taskKey,
                request.title(), request.evidenceUrl(), request.description()
        );
    }

    public record ApplyRequest(@Min(0) long expectedRoadmapVersion) {
    }

    public record TaskStateRequest(@NotBlank String state) {
    }

    public record TaskEvidenceRequest(
            @NotBlank String title,
            @NotBlank String evidenceUrl,
            @NotBlank String description
    ) {
    }
}
