package com.jobiss.posting;

import com.jobiss.common.ApiException;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PostingContentQualityTest {

    @Test
    void acceptsARealisticPostingBody() {
        String posting = """
                JOBIS 백엔드 개발자 채용
                주요 업무
                Java와 Spring Boot로 REST API를 설계하고 운영합니다.
                MySQL 쿼리를 개선하고 서비스 장애 원인을 분석합니다.
                자격요건
                Java 기반 웹 애플리케이션 개발 경험이 필요합니다.
                Git을 활용한 협업 경험과 네트워크 기본 지식을 요구합니다.
                우대사항
                Redis, Kafka 또는 AWS 운영 경험을 우대합니다.
                팀원과 코드 리뷰를 수행하고 테스트 코드를 작성합니다.
                """;

        assertThatCode(() -> PostingContentQuality.requireSufficient(posting))
                .doesNotThrowAnyException();
    }

    @Test
    void rejectsNavigationChromeWithoutJobRequirements() {
        String pageChrome = """
                로그인 회원가입 채용정보 기업정보 인재검색
                지역별 직무별 검색 최근 본 공고 관심기업 고객센터
                홈 채용공고 검색 결과 백엔드 검색 메뉴 전체보기
                로그인하면 맞춤 공고를 확인할 수 있습니다.
                추천 검색어 인기 채용 기업 서비스 소개 이용약관 개인정보처리방침
                """;

        assertThatThrownBy(() -> PostingContentQuality.requireSufficient(pageChrome))
                .isInstanceOf(ApiException.class)
                .extracting(exception -> ((ApiException) exception).code())
                .isEqualTo("POSTING_SOURCE_INSUFFICIENT");
    }
}
