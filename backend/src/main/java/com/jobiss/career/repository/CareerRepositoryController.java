package com.jobiss.career.repository;

import jakarta.validation.Valid;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api")
public class CareerRepositoryController {

    private final CareerRepositoryService service;

    public CareerRepositoryController(CareerRepositoryService service) {
        this.service = service;
    }

    @PostMapping("/career-sources")
    CareerRepositoryService.SourceDetail createSource(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody CreateSourceRequest request
    ) {
        return service.create(
                userId,
                new CareerRepositoryService.CreateSource(
                        request.sourceType(),
                        request.title(),
                        request.sourceUrl(),
                        request.rawText()
                )
        );
    }

    @GetMapping("/career-sources")
    List<CareerRepositoryService.SourceSummary> listSources(
            @AuthenticationPrincipal UUID userId,
            @RequestParam(defaultValue = "false") boolean archived
    ) {
        return service.listSources(userId, archived);
    }

    @GetMapping("/career-sources/{sourceId}")
    CareerRepositoryService.SourceDetail getSource(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sourceId
    ) {
        return service.getSource(userId, sourceId);
    }

    @PostMapping("/career-sources/{sourceId}/retry")
    ResponseEntity<Void> retrySource(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sourceId
    ) {
        service.retrySource(userId, sourceId);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/career-sources/{sourceId}/confirm")
    ResponseEntity<Void> confirmSource(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sourceId,
            @Valid @RequestBody ConfirmSourceRequest request
    ) {
        service.confirmSource(userId, sourceId, request.fragmentIds());
        return ResponseEntity.noContent().build();
    }

    @DeleteMapping("/career-sources/{sourceId}")
    ResponseEntity<Void> deleteSource(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sourceId
    ) {
        service.deleteSource(userId, sourceId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/career-fragments")
    CareerRepositoryService.FragmentPage searchFragments(
            @AuthenticationPrincipal UUID userId,
            @RequestParam(defaultValue = "") String query,
            @RequestParam(defaultValue = "") String kind,
            @RequestParam(defaultValue = "CONFIRMED") String status,
            @RequestParam(defaultValue = "createdAt") String sort,
            @RequestParam(defaultValue = "desc") String direction,
            @RequestParam(defaultValue = "false") boolean archived,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "30") int size
    ) {
        return service.searchFragments(
                userId,
                query,
                kind,
                status,
                sort,
                direction,
                archived,
                page,
                size
        );
    }

    @PatchMapping("/career-fragments/{fragmentId}")
    CareerRepositoryService.FragmentView updateFragment(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID fragmentId,
            @Valid @RequestBody UpdateFragmentRequest request
    ) {
        return service.updateFragment(userId, fragmentId, request.toCommand());
    }

    @PostMapping("/career-fragments/merge")
    CareerRepositoryService.FragmentView mergeFragments(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody MergeFragmentsRequest request
    ) {
        return service.mergeFragments(
                userId,
                request.fragmentIds(),
                request.fragment().toCommand()
        );
    }

    @PostMapping("/career-fragments/{fragmentId}/archive")
    ResponseEntity<Void> archiveFragment(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID fragmentId
    ) {
        service.archiveFragment(userId, fragmentId, true);
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/career-fragments/{fragmentId}/restore")
    ResponseEntity<Void> restoreFragment(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID fragmentId
    ) {
        service.archiveFragment(userId, fragmentId, false);
        return ResponseEntity.noContent().build();
    }

    @DeleteMapping("/career-fragments/{fragmentId}")
    ResponseEntity<Void> deleteFragment(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID fragmentId
    ) {
        service.deleteFragment(userId, fragmentId);
        return ResponseEntity.noContent().build();
    }

    public record CreateSourceRequest(
            @NotBlank
            @Pattern(regexp = "TEXT|FILE|URL")
            String sourceType,
            @NotBlank
            @Size(max = 180)
            String title,
            @Size(max = 2_000)
            String sourceUrl,
            @NotBlank
            @Size(min = 20, max = 100_000)
            String rawText
    ) {
        @AssertTrue(message = "URL 방식에서는 sourceUrl이 필요합니다.")
        public boolean isSourceConsistent() {
            return !"URL".equals(sourceType)
                    || (sourceUrl != null && !sourceUrl.isBlank());
        }
    }

    public record ConfirmSourceRequest(
            @NotEmpty @Size(max = 100) List<UUID> fragmentIds
    ) {
    }

    public record UpdateFragmentRequest(
            @NotBlank
            @Pattern(regexp = "SKILL|PROJECT|EXPERIENCE|EDUCATION|CREDENTIAL|ACHIEVEMENT|LINK")
            String kind,
            @NotBlank @Size(max = 180) String title,
            @Size(max = 4_000) String description,
            @Pattern(regexp = "^[a-z0-9][a-z0-9._:-]{2,159}$")
            String canonicalKey,
            JsonNode detail
    ) {
        CareerRepositoryService.UpdateFragment toCommand() {
            return new CareerRepositoryService.UpdateFragment(
                    kind,
                    title,
                    description == null ? "" : description,
                    canonicalKey,
                    detail
            );
        }
    }

    public record MergeFragmentsRequest(
            @NotEmpty @Size(min = 2, max = 50) List<UUID> fragmentIds,
            @Valid UpdateFragmentRequest fragment
    ) {
    }
}
