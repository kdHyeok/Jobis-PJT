"""전담 에이전트 레지스트리 (개선방안 §2.2 MVP 로스터).

각 에이전트는 세션 자산(dict)을 받아 AgentResult 를 반환하는 진입 함수 하나로 노출된다.
오케스트레이터(dispatch_router)는 이 레지스트리에 등록된 이름만 호출할 수 있다 —
"알려진 도구 중에서만 고른다"(agent_develop §3.6-1)를 코드로 강제하는 지점.

에이전트는 판정을 하지 않는다. 판정이 필요하면 판정 엔진(fit_analysis → build_graph)을
부르고, 생성 에이전트는 판정 산출물의 소비자로만 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AgentResult:
    """에이전트 실행 결과. reply 는 대화로 나가는 문장, data 는 구조화 산출물."""

    reply: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)
    followUpQuestions: list[dict] = field(default_factory=list)
    # 세션에 저장할 자산 (예: {"analysis": {...}}) — 오케스트레이터가 세션에 병합한다.
    sessionUpdates: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentSpec:
    """capability manifest 의 한 항목 (agent_develop §3.6 capability manifest).

    **도구(tool)와 에이전트(agent)를 구분한다.** 구분의 기준은 하나다 — *말을 하는가.*

      · tool  = 결정론 계산. 같은 입력이면 같은 출력. **사용자향 문장을 만들지 않는다**
                (`entry` 는 reply 를 비우고 데이터만 낸다). 문장은 `render` 가 만든다.
                자율 루프도, 여러 턴 상태도 없다 — 재선택할 것이 없으므로 관찰도 걸지 않는다.
      · agent = 판단·표현. LLM 으로 자유도를 갖고, 필요하면 자기 루프(agent_loop)를 돌며
                여러 턴 상태를 갖는다. 대신 사용자향 문장은 검증(금지표현)을 통과해야 한다.

    전에는 둘이 한 스펙에 뭉뚱그려져 있었다. 그래서 정확해야 할 결정론(매칭·점수·연차
    필터)과 자유도가 필요한 것(대화·초안)이 같은 취급을 받았고, "무엇이 에이전트인가"가
    코드에 존재하지 않았다. 이 구분이 에이전트 개념의 본질이다.
    """

    name: str
    description: str
    # 세션 자산 전제조건(전부 필요): "resume" | "job_posting" | "analysis" | "roadmap"
    preconditions: tuple[str, ...]
    entry: Callable[[dict], AgentResult]
    # "tool" | "agent" — 위 docstring 의 구분. 기본은 agent(기존 항목 동작 보존).
    kind: str = "agent"
    # 도구 전용: (데이터, 세션) → (사용자향 문장, 경고). 도구의 entry 는 reply 를 비우므로 이것이
    # 없으면 그 도구는 아무 말도 하지 못한다(그래서 도구는 render 를 반드시 갖는다 — 테스트가
    # 강제). **경고를 함께 돌려주는 이유**: 표현 계층도 LLM 을 쓸 수 있고(fit_analysis 의 다음
    # 행동 제안), 문장만 돌려주면 그 호출이 왜 폴백됐는지가 사라진다 — 폴백이 이유를 삼키는
    # 것은 이 코드베이스가 반복해서 대가를 치른 실수다(0728 §6, 0729 §3).
    #
    # **세션도 받는다**(0729): 마무리 문장은 "사용자가 방금 한 말에 이어지게" 써야 하므로 발화·
    # 대화 이력이 필요하다. 그것을 data 로 흘리면 프론트로 나가는 산출물 계약에 대화 이력이
    # 섞인다 — 표현이 필요한 맥락은 표현 계층이 직접 읽는다. 읽기 전용이다.
    render: Callable[[dict, dict], tuple[str, list[dict]]] | None = None
    # 이 에이전트가 받는 **인자** — (이름, 설명). 플래너 프롬프트의 manifest 에 그대로 실려
    # LLM 이 값을 정한다. 지금까지 LLM 은 "누가 실행할지"만 골랐고 "무엇으로"는 전부 세션에서
    # 왔다(블랙보드). 그래서 "데이터 엔지니어 공고 찾아줘" 처럼 발화에만 있는 대상을 전달할
    # 통로가 없었다. 인자는 **선택**이다 — 안 오면 에이전트는 기존대로 세션만 보고 동작한다.
    # 값은 검증기가 선언된 이름만 통과시킨다(미선언 인자 환각 차단).
    params: tuple[tuple[str, str], ...] = ()
    # 인자가 전제 자산을 **대신할 수 있으면** (인자이름, 자산이름) 으로 선언한다.
    # 예: 발화에 직군이 명시되면(job_name) 그것이 곧 사용자가 밝힌 선호이므로, 선호를
    # 모으는 선행 에이전트를 끼울 이유가 없다. 이 선언이 없으면 인자가 와도 전제는 그대로다.
    params_satisfy: tuple[tuple[str, str], ...] = ()
    # 대안 전제 — 이 중 **하나라도** 있으면 충족(AND 전제와 함께 쓸 수 있다). 같은 일을
    # 여러 자산으로 할 수 있는 에이전트를 "가장 좋은 자산이 없으면 불가"로 만들지 않기 위한 것.
    # 예: job_recommend 는 이력서(역량 일치까지 계산)로도, 대화로 모은 선호(선호 기준 추천)로도
    # 실공고를 추천할 수 있다. 하나도 없으면 검증기가 이 중 만들 수 있는 자산의 생산자를 끼운다
    # (선언 순서가 곧 우선순위 — 앞에 쓴 자산을 먼저 시도).
    preconditions_any: tuple[str, ...] = ()
    # 실행 성공 시 세션에 생기는 자산 — 플래너 검증기가 전제 자동 삽입을 추론하는 근거.
    produces: tuple[str, ...] = ()
    # 무거운 파이프라인(LLM 여러 회·수십 초) 여부. 검증기가 이 에이전트를 **자동 삽입**할 때는
    # 말없이 시작하지 않고 사용자에게 먼저 묻는다(동의 게이트). 명시 선택이면 그대로 실행.
    heavy: bool = False
    # 플래너에 보이지 않는 항목(manifest 제외) — 호출은 오케스트레이터의 결정론 규칙만 한다.
    # 자산 상태에서 따라 나오는 필연적 단계(예: URL 공고 수집)는 LLM 이 고를 판단이 아니고,
    # manifest 에 넣으면 플래너 어휘가 바뀌어 평가셋 재측정이 필요해진다(AGENTS.md §3-1·§3-6).
    internal: bool = False


def get_agent_registry() -> dict[str, AgentSpec]:
    """이름 → AgentSpec. 함수로 감싼 것은 순환 import 방지(에이전트가 그래프/서비스를 임포트)."""

    from jobis_ai.agents import (
        application_plan,
        career_chat,
        coverletter_draft,
        fit_analysis,
        interview_prep,
        job_recommend,
        posting_analysis,
        posting_fetch,
        preference_intake,
        resume_diagnosis,
        roadmap_manager,
        tool_render,
    )

    specs = [
        AgentSpec(
            name="posting_fetch",
            description="공고 URL 수집 — URL 자산을 원문 텍스트 자산으로 승격 (파싱은 posting_analysis 의 일)",
            preconditions=("job_posting",),
            entry=posting_fetch.run,
            kind="tool",
            render=tool_render.render_posting_fetch,
            internal=True,   # 플래너가 아니라 오케스트레이터가 결정론으로 끼운다(chat.py, D64)
        ),
        AgentSpec(
            name="fit_analysis",
            description="공고×이력서 적합도 판정 (기존 판정 엔진 전체)",
            preconditions=("resume", "job_posting"),
            entry=fit_analysis.run,
            kind="tool",
            render=tool_render.render_fit_analysis,
            # 대화 세션의 임시 로드맵을 만들지 않는다. 로드맵 정본은 백엔드 UNIFIED
            # 분석이 영속화하고 roadmap_manager는 그 DB 스냅샷만 조회한다.
            produces=("analysis",),
            heavy=True,
            # 여러 공고를 각각 판정해 달라는 요청(D88) — 정리된 공고 목록([세션 자산 상태])의
            # 회사명으로 지목한다. 도구가 내부에서 대상별로 반복 판정한다.
            # 판정은 이력서×공고라 축이 둘이다 — 이력서 축은 resumeTargets(D119).
            params=(("targets", "사용자가 활성 공고가 아닌 **다른 공고를 지목했을 때** — 정리된 "
                     "공고 목록·추천 공고 목록의 회사명을 쉼표로 구분해 적는다. 추천 공고를 "
                     "순번으로 지목하면(\"두 번째 추천 공고\") 숫자만 적는다(\"2\"). "
                     "\"각각\"·\"둘 다\" 같은 복수 "
                     "요청이면 해당 회사명을 전부 적는다(비교). 하나만 지목하면 그 공고가 활성 "
                     "공고가 되어 **뒤에 오는 자소서·면접도 그 공고 기준**이 된다 — 예전에 정리한 "
                     "공고로 자소서·면접을 청하면 여기에 그 회사명을 적어야 한다. "
                     "예: 원더스랩, 오로라월드"),
                    ("resumeTargets",
                     ("사용자가 **이력서 쪽을 지목했을 때** — 이력서 목록의 "
                      "라벨(\"커리어 저장소\"·\"붙여넣은 이력서\"·파일명)이나 순번을 쉼표로 "
                      "구분해 적는다. 둘 이상이면 **같은 공고에 이력서별로** 판정한다"
                      "(\"A와 B 중 어느 이력서가 나아?\"). 하나면 그 이력서를 활성으로 바꿔 "
                      "판정한다 — 뒤에 오는 자소서·면접도 그 이력서 기준이 된다.")),),
        ),
        AgentSpec(
            name="posting_analysis",
            # 대화형 승격(D97) — 공고 질문의 **담당**이다. 정의를 넓힌 것이 아니라 원래 이
            # 자산으로 답할 수 있던 범위를 적은 것이다: 실측(2026-07-31)에서 "이 공고 기준으로
            # 무엇을 공부할까"가 어느 항목에도 안 적혀 있어 플래너가 이력서를 요구하는 쪽으로 갔다.
            description=("공고 담당 대화 — 공고에 관한 질문을 **공고 원문 근거로** 받는다: 요구사항 정리"
                         "(필수·우대·기술 스택·요구 연차), 요건의 뜻·우선순위 풀이, **이 공고 기준으로 "
                         "무엇을 공부하고 어떤 프로젝트를 만들면 좋은지**, 원문에 적힌 전형·근무 형태. "
                         "**이력서 없이 가능하다** — 사용자 정보를 요구하지 않는다. 적합도 판정은 안 함"),
            preconditions=("job_posting",),
            entry=posting_analysis.run,
        ),
        AgentSpec(
            name="job_recommend",
            description=("실공고 DB 에서 공고 추천 — 이력서가 있으면 보유 역량 일치까지 계산하고, "
                         "이력서가 없으면 대화로 수집한 선호(직군·도메인·회사·지역·기술스택) 기준으로 추천"),
            preconditions=(),
            preconditions_any=("resume", "preferences"),
            entry=job_recommend.run,
            kind="tool",
            render=tool_render.render_job_recommend,
            produces=("recommendations",),
            # 발화에 직군이 명시되면 그것으로 바로 찾는다 — 선호 수집을 거치지 않아도 된다.
            # (프로토타입 search_postings(job_name) 계약과 같은 자리.)
            params=(("job_name", "찾을 직군·직무 이름. 발화에 명시됐을 때만. 예: 데이터 엔지니어"),),
            params_satisfy=(("job_name", "preferences"),),
        ),
        AgentSpec(
            name="career_chat",
            description=("**어떤 기능도 요청하지 않은** 발화(진로 고민·하소연·인사·감사·일반 상식 질문)를 "
                         "받아주는 대화 — 필요할 때만 기능을 부드럽게 안내. **기능을 요청했는데 자료가 "
                         "부족한 경우는 여기가 아니다**(그때는 가진 자료로 할 수 있는 기능을 고른다). "
                         "단, **가진 자산이 하나도 없어 청한 기능을 위한 어떤 준비도 지금 불가**하면 "
                         "여기가 턴을 받아 필요한 자료(이력서·공고)를 대화로 청한다"),
            preconditions=(),
            entry=career_chat.run,
        ),
        AgentSpec(
            name="preference_intake",
            description=("**공고를 찾아·추천해 달라는 요청에만** 쓰는 선호(직군·회사·도메인) 수집 대화. "
                         "이력서 진단·적합도 판정·로드맵 등 **다른 기능의 자료가 없을 때 대신 고르는 "
                         "곳이 아니다** — 그때는 career_chat 이 필요한 자료를 청한다"),
            preconditions=(),
            entry=preference_intake.run,
            produces=("preferences",),
        ),
        AgentSpec(
            name="resume_diagnosis",
            # 대화형 승격(D97 의 짝) — 이력서 질문의 **담당**이다. 항목화 사실만 내던 시절에는
            # "내 강점이 뭐야"·"이 프로젝트를 어떻게 써야 해" 의 담당이 없었다.
            # 승격으로 능력 서술을 늘리면서 **"대신 할 수 있는 일"이라는 역할 문장을 지웠더니**
            # `fit-missing-posting-degrade`(이력서만 있는데 적합도 요청)가 1.00 → 0.67 로
            # 깨졌다(2026-08-01 재측정, career_chat 으로 1/3 이탈). 그 문장이 그 케이스의
            # 라우팅 근거였다 — 능력과 역할은 다른 정보이고 둘 다 있어야 한다.
            description=("이력서 담당 대화 — 이력서에 관한 질문을 **이력서 근거로** 받는다: 읽어낸 항목 정리"
                         "(기술·프로젝트·경력·학력·자격·어학), **경험으로 뒷받침되는 강점 정리**, 이름만 "
                         "적힌 스킬·빈 섹션의 보강 방향, 원문에 적힌 서술·성과 확인. 적합도 판정은 안 함. "
                         "**공고가 없어 적합도 판정·자소서·면접을 못 할 때 이력서로 먼저 할 수 있는 "
                         "일**이다"),
            preconditions=("resume",),
            entry=resume_diagnosis.run,
            # 이력서가 여럿일 때 지목(D119) — 공고 쪽 fit_analysis.targets 와 같은 규약.
            params=(("targets",
                     ("사용자가 **어느 이력서인지 지목했을 때** — 이력서 목록의 "
                      "라벨(\"커리어 저장소\"·\"붙여넣은 이력서\"·파일명)이나 순번을 쉼표로 "
                      "구분해 적는다. \"둘 다\"·\"비교\" 같은 복수 요청이면 해당하는 것을 "
                      "전부 적는다(비교). 하나만 지목하면 그 이력서가 활성이 된다.")),),
        ),
        AgentSpec(
            name="interview_prep",
            description=("면접 연습 진행 — 판정 결과에서 소재를 골라 한 번에 한 질문씩 묻고, "
                         "사용자 답변을 점검해 꼬리 질문으로 파고든다(여러 턴 이어짐)"),
            preconditions=("analysis",),
            entry=interview_prep.run,
            # 여러 턴에 걸친 진행 상태를 만든다 — 다음 턴이 이어받는다.
            produces=("interview",),
            params=(("focus", "이번에 다룰 주제·기술을 사용자가 지목했을 때만. 예: React"),),
        ),
        AgentSpec(
            name="coverletter_draft",
            description=("적합도 분석 근거 기반 자소서 초안 — 쓰고 스스로 점검해 고친다. "
                         "이미 초안이 있으면 지목된 문단만 다시 다듬는다 (항상 사용자 검토 게이트)"),
            preconditions=("resume", "analysis"),
            entry=coverletter_draft.run,
            produces=("coverletter",),
            params=(("focus", "다시 다듬을 문단·주제를 사용자가 지목했을 때만. 예: 강점 문단"),),
        ),
        AgentSpec(
            name="application_plan",
            description="적합도 판정 결과로 '지금 목표로 둘지'(목표 상태)와 지원 경로 2~3개를 세운다 — 판정은 룰, 문구는 LLM",
            preconditions=("analysis",),
            entry=application_plan.run,
            produces=("application_plan",),
        ),
        AgentSpec(
            name="roadmap_manager",
            description="저장된 준비 로드맵 조회 (수정·진척은 후속)",
            preconditions=("roadmap",),
            entry=roadmap_manager.run,
            kind="tool",
            render=tool_render.render_roadmap_manager,
        ),
    ]
    return {s.name: s for s in specs}
