-- 상태 카드(kind = ANALYSIS_STATUS)는 의도적으로 본문이 없다 — 이 턴에 말하는 주체는
-- 에이전트이고, 이 행은 진행/완료/실패 카드가 붙는 자리만 남긴다(08-03 결정,
-- AnalysisWorker 의 카드 insert 주석 참조).
--
-- 그런데 V2 의 content 1자 이상 제약이 그 빈 카드 insert 를 거부해 complete()/fail()
-- 트랜잭션이 통째로 굴러떨어졌고, 분석 job 이 전부 FAILED → 지도 자동 생성까지 막혔다
-- (실측 08-04: conversation_messages_content_check 위반). 카드 kind 에 한해 빈 본문을
-- 허용한다 — 일반 메시지의 빈 본문은 여전히 막는다.
ALTER TABLE conversation_messages
    DROP CONSTRAINT conversation_messages_content_check;
ALTER TABLE conversation_messages
    ADD CONSTRAINT conversation_messages_content_check
    CHECK (
        char_length(content) <= 100000
        AND (kind = 'ANALYSIS_STATUS' OR char_length(content) >= 1)
    );
