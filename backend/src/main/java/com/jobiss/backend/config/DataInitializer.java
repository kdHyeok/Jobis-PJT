package com.jobiss.backend.config;

import com.jobiss.backend.domain.Evidence;
import com.jobiss.backend.domain.EvidenceKind;
import com.jobiss.backend.domain.JobPosting;
import com.jobiss.backend.domain.JobSourceType;
import com.jobiss.backend.domain.User;
import com.jobiss.backend.repository.EvidenceRepository;
import com.jobiss.backend.repository.JobPostingRepository;
import com.jobiss.backend.repository.UserRepository;
import org.springframework.boot.CommandLineRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * 시작 시 데모용 시드 데이터를 넣는다(비어있을 때만).
 * - 샘플 공고 4건 (목업 JOBS)
 * - 데모 사용자(박준영) + 커리어 자료 6건 (목업 EVIDENCES)
 */
@Component
public class DataInitializer implements CommandLineRunner {

    private final JobPostingRepository jobPostingRepository;
    private final UserRepository userRepository;
    private final EvidenceRepository evidenceRepository;
    private final PasswordEncoder passwordEncoder;

    public DataInitializer(JobPostingRepository jobPostingRepository, UserRepository userRepository,
                           EvidenceRepository evidenceRepository, PasswordEncoder passwordEncoder) {
        this.jobPostingRepository = jobPostingRepository;
        this.userRepository = userRepository;
        this.evidenceRepository = evidenceRepository;
        this.passwordEncoder = passwordEncoder;
    }

    @Override
    @Transactional
    public void run(String... args) {
        if (jobPostingRepository.findBySourceType(JobSourceType.SAMPLE).isEmpty()) {
            seedSampleJobPostings();
        }
        if (!userRepository.existsByEmail("junyoung.park@gmail.com")) {
            seedDemoUser();
        }
    }

    private void seedSampleJobPostings() {
        jobPostingRepository.save(sample("cloudwave", "클라우드웨이브", "백엔드 엔지니어 (Java/Spring)",
                "3년 이상", "7. 31.", "https://careers.cloudwave.kr/jobs/backend-engineer-2026",
                "[\"Java\",\"Spring Boot\",\"JPA\",\"MySQL\",\"AWS\",\"Docker\"]"));
        jobPostingRepository.save(sample("nextcommerce", "넥스트커머스", "백엔드 개발자 (Java)",
                "신입", "8. 8.", "https://careers.nextcommerce.kr/jobs/backend-junior",
                "[\"Java\",\"Spring\",\"MySQL\"]"));
        jobPostingRepository.save(sample("dataline", "데이터라인", "주니어 서버 개발자 (Kotlin)",
                "신입", "8. 15.", "https://careers.dataline.io/jobs/junior-server",
                "[\"Kotlin\",\"Spring\",\"JPA\"]"));
        jobPostingRepository.save(sample("highbridge", "하이브릿지", "플랫폼 서버 개발자",
                "신입", "8. 22.", "https://careers.highbridge.kr/jobs/platform-server",
                "[\"Java\",\"Spring Boot\",\"Redis\"]"));
    }

    private JobPosting sample(String code, String company, String role, String career,
                              String due, String url, String stackJson) {
        return JobPosting.builder()
                .code(code)
                .sourceType(JobSourceType.SAMPLE)
                .company(company)
                .role(role)
                .career(career)
                .due(due)
                .url(url)
                .stack(stackJson)
                .build();
    }

    private void seedDemoUser() {
        User user = User.builder()
                .email("junyoung.park@gmail.com")
                .passwordHash(passwordEncoder.encode("test1234"))
                .name("박준영")
                .build();   // status 는 기본 ACTIVE
        userRepository.save(user);

        // "가진 사실"만 시드 — 없는 것(자격증 미입력 등)은 행을 만들지 않는다(status 폐지).
        evidenceRepository.save(evidence(user, EvidenceKind.PROJECT, "Spring Boot 게시판 REST API",
                "Java · Spring Boot · JPA · MySQL — 목록 API 1.2s → 180ms"));
        evidenceRepository.save(evidence(user, EvidenceKind.GITHUB, "GitHub — github.com/junyoung-p",
                "커밋 214건 · 테스트 폴더 없음 · 단독 커밋 96%"));
        evidenceRepository.save(evidence(user, EvidenceKind.PORTFOLIO, "포트폴리오_박준영_v2.pdf",
                "18쪽 · 성과 수치 포함"));
        evidenceRepository.save(evidence(user, EvidenceKind.STACK, "기술 스택",
                "Java · Spring · MySQL · Python"));
        evidenceRepository.save(evidence(user, EvidenceKind.EDU, "교육 이력",
                "SSAFY / KDT 지원 준비 중"));
    }

    private Evidence evidence(User user, EvidenceKind kind, String label, String desc) {
        return Evidence.builder()
                .user(user).kind(kind).label(label).description(desc).build();
    }
}
