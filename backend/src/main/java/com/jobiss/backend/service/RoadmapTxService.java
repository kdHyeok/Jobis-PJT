package com.jobiss.backend.service;

import com.jobiss.backend.domain.AnalysisRun;
import com.jobiss.backend.domain.JobPosting;
import com.jobiss.backend.domain.RoadmapStepProgress;
import com.jobiss.backend.domain.RoadmapStepStatus;
import com.jobiss.backend.domain.AnalysisResult;
import com.jobiss.backend.domain.RoadmapStageDetail;
import com.jobiss.backend.domain.SavedRoadmap;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.repository.AnalysisResultRepository;
import com.jobiss.backend.repository.AnalysisRunRepository;
import com.jobiss.backend.repository.RoadmapStageDetailRepository;
import com.jobiss.backend.repository.RoadmapStepProgressRepository;
import com.jobiss.backend.repository.SavedRoadmapRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

/**
 * 로드맵 생성의 DB 경계(짧은 트랜잭션). 외부 AI HTTP 호출은 이 트랜잭션 밖에서 일어나야
 * 커넥션을 오래 물지 않는다. SavedRoadmapService 가 load()(읽기) → AI 호출 → upsert()(쓰기) 로 orchestrate.
 */
@Service
public class RoadmapTxService {

    private final AnalysisRunRepository runRepository;
    private final SavedRoadmapRepository savedRepository;
    private final RoadmapStepProgressRepository progressRepository;
    private final AnalysisResultRepository resultRepository;
    private final RoadmapStageDetailRepository stageDetailRepository;

    public RoadmapTxService(AnalysisRunRepository runRepository, SavedRoadmapRepository savedRepository,
                            RoadmapStepProgressRepository progressRepository,
                            AnalysisResultRepository resultRepository,
                            RoadmapStageDetailRepository stageDetailRepository) {
        this.runRepository = runRepository;
        this.savedRepository = savedRepository;
        this.progressRepository = progressRepository;
        this.resultRepository = resultRepository;
        this.stageDetailRepository = stageDetailRepository;
    }

    /** 분석 소유권 확인 + AI 호출 맥락(회사·직무·목표맥락)을 트랜잭션 안에서 추출(LAZY 연관 로딩). */
    @Transactional(readOnly = true)
    public RoadmapContext load(Long userId, String analysisId, String routeKind) {
        AnalysisRun run = runRepository.findByAnalysisId(analysisId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "분석을 찾을 수 없습니다."));
        if (!run.getUser().getId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "접근 권한이 없습니다.");
        }
        JobPosting job = run.getJobPosting();

        String goalCompany = null;
        String goalLabel = null;
        String parentId = run.getParentAnalysisId();
        if (parentId != null) {
            AnalysisRun parent = runRepository.findByAnalysisId(parentId).orElse(null);
            if (parent != null) {
                JobPosting pj = parent.getJobPosting();
                goalCompany = pj.getCompany();
                String c = pj.getCompany() == null ? "" : pj.getCompany();
                String r = pj.getRole() == null ? "" : pj.getRole();
                String label = (c + (r.isBlank() ? "" : " · " + r)).trim();
                goalLabel = label.isBlank() ? null : cap(label, 200);   // goal_label VARCHAR(200)
            }
        }
        return new RoadmapContext(job.getCompany(), job.getRole(), routeKind, goalCompany, goalLabel);
    }

    /** 생성된 로드맵 저장(같은 user+analysis+route면 교체). 짧은 쓰기 트랜잭션. */
    @Transactional
    public SavedRoadmap upsert(Long userId, String analysisId, String routeId, String goalLabel, String roadmapJson) {
        return savedRepository.findByUserIdAndAnalysisIdAndRouteId(userId, analysisId, routeId)
                .map(existing -> {
                    existing.updateRoadmap(goalLabel, roadmapJson);
                    return savedRepository.save(existing);
                })
                .orElseGet(() -> savedRepository.save(SavedRoadmap.builder()
                        .userId(userId).analysisId(analysisId).routeId(routeId)
                        .goalLabel(goalLabel).roadmapJson(roadmapJson).build()));
    }

    /** 로드맵 저장소 목록(내 것, 최신순). */
    @Transactional(readOnly = true)
    public List<SavedRoadmap> listForUser(Long userId) {
        return savedRepository.findByUserIdOrderByCreatedAtDesc(userId);
    }

    /** 단건 조회(로드맵 페이지용) — (분석·경로)로 저장된 로드맵 하나. */
    @Transactional(readOnly = true)
    public SavedRoadmap findOne(Long userId, String analysisId, String routeId) {
        return savedRepository.findByUserIdAndAnalysisIdAndRouteId(userId, analysisId, routeId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "ROADMAP_NOT_FOUND",
                        "저장된 로드맵이 없어요. 먼저 '로드맵 생성'을 눌러주세요."));
    }

    /** 한 로드맵(분석·경로)의 스텝별 진행 상태(로드맵 페이지에서 요건 매트릭스·상태에 사용). */
    @Transactional(readOnly = true)
    public List<RoadmapStepProgress> progressFor(Long userId, String analysisId, String routeId) {
        return progressRepository.findByUserIdAndAnalysisIdAndRouteId(userId, analysisId, routeId);
    }

    /** 스텝 재진단 결과 저장(같은 스텝이면 최신 제출로 교체). 짧은 쓰기 트랜잭션. */
    @Transactional
    public RoadmapStepProgress upsertProgress(Long userId, String analysisId, String routeId, int stepNo,
                                              RoadmapStepStatus status, String submittedUrl, String verdictJson) {
        return progressRepository.findByUserIdAndAnalysisIdAndRouteIdAndStepNo(userId, analysisId, routeId, stepNo)
                .map(existing -> {
                    existing.update(status, submittedUrl, verdictJson);
                    return progressRepository.save(existing);
                })
                .orElseGet(() -> progressRepository.save(RoadmapStepProgress.builder()
                        .userId(userId).analysisId(analysisId).routeId(routeId).stepNo(stepNo)
                        .status(status).submittedUrl(submittedUrl).verdictJson(verdictJson).build()));
    }

    /** 대표 로드맵 지정 — 한 사용자에 대표는 하나(나머지 해제 후 지정). */
    @Transactional
    public SavedRoadmap setRepresentative(Long userId, Long id) {
        SavedRoadmap target = savedRepository.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "ROADMAP_NOT_FOUND", "로드맵을 찾을 수 없습니다."));
        if (!target.getUserId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "접근 권한이 없습니다.");
        }
        for (SavedRoadmap sr : savedRepository.findByUserIdOrderByCreatedAtDesc(userId)) {
            sr.setRepresentative(sr.getId().equals(id));   // 대상만 true, 나머지 false (dirty checking으로 반영)
        }
        return target;
    }

    /** 저장 로드맵 1개 삭제(+그 스텝 진행). 소유권 확인. */
    @Transactional
    public void deleteRoadmap(Long userId, Long id) {
        SavedRoadmap sr = savedRepository.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "ROADMAP_NOT_FOUND", "로드맵을 찾을 수 없습니다."));
        if (!sr.getUserId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "접근 권한이 없습니다.");
        }
        progressRepository.findByUserIdAndAnalysisIdAndRouteId(userId, sr.getAnalysisId(), sr.getRouteId())
                .forEach(progressRepository::delete);
        savedRepository.delete(sr);
    }

    private static String cap(String s, int n) {
        if (s == null) return null;
        return s.length() > n ? s.substring(0, n) : s;
    }

    // ── 단계형(staged) 로드맵 ─────────────────────────────────────────

    /** staged 개요 생성용 맥락 — 회사·직무 + 분석 결과 JSON(격차·판정). AI 호출은 트랜잭션 밖에서. */
    @Transactional(readOnly = true)
    public StagedContext loadStaged(Long userId, String analysisId) {
        AnalysisRun run = runRepository.findByAnalysisId(analysisId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "분석을 찾을 수 없습니다."));
        if (!run.getUser().getId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "접근 권한이 없습니다.");
        }
        JobPosting job = run.getJobPosting();
        String resultJson = resultRepository.findByRunId(run.getId())
                .map(AnalysisResult::getResult).orElse(null);
        return new StagedContext(job.getCompany(), job.getRole(), resultJson);
    }

    /** 단계 상세 캐시 조회. */
    @Transactional(readOnly = true)
    public Optional<RoadmapStageDetail> findDetail(Long savedRoadmapId, int stageNo) {
        return stageDetailRepository.findBySavedRoadmapIdAndStageNo(savedRoadmapId, stageNo);
    }

    /** 단계 상세 캐시 저장(있으면 교체). 짧은 쓰기 트랜잭션. */
    @Transactional
    public RoadmapStageDetail saveDetail(Long savedRoadmapId, int stageNo, String detailJson) {
        return stageDetailRepository.findBySavedRoadmapIdAndStageNo(savedRoadmapId, stageNo)
                .map(existing -> { existing.updateDetail(detailJson); return stageDetailRepository.save(existing); })
                .orElseGet(() -> stageDetailRepository.save(RoadmapStageDetail.builder()
                        .savedRoadmapId(savedRoadmapId).stageNo(stageNo).detailJson(detailJson).build()));
    }

    /** staged 개요 생성 맥락 스냅샷(트랜잭션 밖으로 안전하게 전달). */
    public record StagedContext(String company, String role, String resultJson) {
    }

    /** AI 호출에 넘길 맥락 스냅샷(트랜잭션 밖으로 안전하게 전달). */
    public record RoadmapContext(String company, String role, String routeKind, String goalCompany, String goalLabel) {
    }
}
