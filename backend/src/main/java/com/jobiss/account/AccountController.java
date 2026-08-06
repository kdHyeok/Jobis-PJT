package com.jobiss.account;

import com.jobiss.auth.AuthService;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.UUID;

@RestController
@RequestMapping("/api/account")
public class AccountController {

    private final AccountService service;

    public AccountController(AccountService service) {
        this.service = service;
    }

    @PatchMapping("/profile")
    AuthService.UserView updateProfile(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody UpdateProfileRequest request
    ) {
        return service.updateProfile(userId, request.email(), request.displayName());
    }

    @PostMapping("/password")
    void changePassword(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody ChangePasswordRequest request,
            HttpServletResponse response
    ) {
        service.changePassword(userId, request.currentPassword(), request.newPassword());
        clearSessionCookies(response);
    }

    @GetMapping(value = "/export", produces = MediaType.APPLICATION_JSON_VALUE)
    JsonNode exportData(@AuthenticationPrincipal UUID userId, HttpServletResponse response) {
        response.setHeader(
                HttpHeaders.CONTENT_DISPOSITION,
                ContentDisposition.attachment()
                        .filename("jobis-data-export.json", StandardCharsets.UTF_8)
                        .build()
                        .toString()
        );
        return service.exportData(userId);
    }

    @DeleteMapping
    AccountService.DeletionReceipt deleteAccount(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody DeleteAccountRequest request,
            HttpServletResponse response
    ) {
        AccountService.DeletionReceipt receipt = service.deleteAccount(userId, request.password());
        clearSessionCookies(response);
        return receipt;
    }

    private void clearAccessCookie(HttpServletResponse response) {
        response.addHeader(
                HttpHeaders.SET_COOKIE,
                "jobiss_access=; Path=/; Max-Age=" + Duration.ZERO.toSeconds() + "; HttpOnly; SameSite=Lax"
        );
    }

    private void clearSessionCookies(HttpServletResponse response) {
        clearAccessCookie(response);
        response.addHeader(
                HttpHeaders.SET_COOKIE,
                "jobiss_refresh=; Path=/; Max-Age=" + Duration.ZERO.toSeconds() + "; HttpOnly; SameSite=Lax"
        );
    }

    public record UpdateProfileRequest(
            @Email @NotBlank @Size(max = 320) String email,
            @NotBlank @Size(max = 80) String displayName
    ) {}

    public record ChangePasswordRequest(
            @NotBlank @Size(max = 100) String currentPassword,
            @NotBlank @Size(min = 12, max = 100) String newPassword
    ) {}

    public record DeleteAccountRequest(@NotBlank @Size(max = 100) String password) {}
}
