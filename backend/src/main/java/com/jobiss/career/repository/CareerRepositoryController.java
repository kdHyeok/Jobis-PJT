package com.jobiss.career.repository;

import com.jobiss.common.WebUrls;
import com.jobiss.common.ApiException;

import jakarta.validation.Valid;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.http.ResponseEntity;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
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
import org.springframework.web.multipart.MultipartFile;
import tools.jackson.databind.JsonNode;

import java.util.List;
import java.util.UUID;
import java.io.IOException;

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

    @PostMapping(
            value = "/career-sources/upload",
            consumes = MediaType.MULTIPART_FORM_DATA_VALUE
    )
    CareerRepositoryService.SourceDetail uploadSource(
            @AuthenticationPrincipal UUID userId,
            @RequestParam(required = false, defaultValue = "") String title,
            @RequestParam("file") MultipartFile file
    ) {
        if (file == null || file.isEmpty()) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "EMPTY_DOCUMENT",
                    "내용이 있는 파일을 선택해 주세요."
            );
        }
        if (file.getSize() > DocumentText.MAX_UPLOAD_BYTES) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "DOCUMENT_TOO_LARGE",
                    "파일은 5MB 이하만 등록할 수 있습니다."
            );
        }
        String originalName = file.getOriginalFilename() == null
                ? "career-document"
                : file.getOriginalFilename().strip();
        String sourceTitle = title == null || title.isBlank()
                ? originalName
                : title.strip();
        if (sourceTitle.isBlank() || sourceTitle.length() > 180) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "INVALID_DOCUMENT_TITLE",
                    "자료 이름은 1자 이상 180자 이하로 입력해 주세요."
            );
        }
        try {
            return service.create(
                    userId,
                    new CareerRepositoryService.CreateSource(
                            "FILE",
                            sourceTitle,
                            null,
                            DocumentText.fromUpload(originalName, file.getBytes())
                    )
            );
        } catch (IOException exception) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "DOCUMENT_READ_FAILED",
                    "업로드한 파일을 읽지 못했습니다."
            );
        }
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

    @PostMapping("/career-sources/{sourceId}/cancel")
    ResponseEntity<Void> cancelSource(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sourceId
    ) {
        service.cancelSource(userId, sourceId);
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

    @PostMapping("/career-sources/{sourceId}/fragments")
    CareerRepositoryService.FragmentView addFragment(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sourceId,
            @Valid @RequestBody AddFragmentRequest request
    ) {
        return service.addSuggestedFragment(
                userId,
                sourceId,
                new CareerRepositoryService.UpdateFragment(
                        request.kind(),
                        request.title(),
                        request.description() == null ? "" : request.description(),
                        null,
                        request.detail()
                )
        );
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
    CareerRepositoryService.MergeResult mergeFragments(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody MergeFragmentsRequest request
    ) {
        return service.mergeFragments(
                userId,
                request.fragmentIds(),
                request.fragment().toCommand()
        );
    }

    @PostMapping("/career-fragments/merge/preview")
    CareerRepositoryService.MergePreview previewMerge(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody MergePreviewRequest request
    ) {
        return service.previewMerge(userId, request.fragmentIds());
    }

    @PostMapping("/career-fragment-merges/{mergeEventId}/undo")
    CareerRepositoryService.FragmentView undoMerge(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID mergeEventId
    ) {
        return service.undoMerge(userId, mergeEventId);
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

        @AssertTrue(message = "자료 URL은 http 또는 https 주소여야 합니다.")
        public boolean isSourceUrlSafe() {
            return WebUrls.isBlankOrHttpUrl(sourceUrl);
        }
    }

    public record ConfirmSourceRequest(
            @NotEmpty @Size(max = 100) List<UUID> fragmentIds
    ) {
    }

    public record AddFragmentRequest(
            @NotBlank
            @Pattern(regexp = "SKILL|PROJECT|EXPERIENCE|EDUCATION|CREDENTIAL|ACHIEVEMENT|LINK")
            String kind,
            @NotBlank @Size(max = 180) String title,
            @Size(max = 4_000) String description,
            JsonNode detail
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

    public record MergePreviewRequest(
            @NotEmpty @Size(min = 2, max = 50) List<UUID> fragmentIds
    ) {
    }
}
