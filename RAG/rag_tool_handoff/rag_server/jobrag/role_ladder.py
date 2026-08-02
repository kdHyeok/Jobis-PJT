"""디딤돌 사다리 — 목표 직군에 도달할 공고가 없을 때 제안할 진입 경로.

⚠ **이 파일의 내용은 대부분 저자의 도메인 판단이다. 검토 대상이다.**
   측정으로 뒷받침된 항목과 판단인 항목을 `basis` 필드로 구분해 적었다.
   틀린 사다리는 "엉뚱한 공고를 자신 있게 추천하는" 결과를 낳으므로,
   도메인 담당자가 반드시 한 번 읽고 고쳐야 한다.

배경 — 왜 필요한가
------------------
`role_taxonomy`는 12종 평면 분류다(계층이 없다). 그런데 실측에서 완전 실패
(상위 3건에 적합 0건)가 특정 직군에 몰렸고, **그 직군들이 정확히 코퍼스 재고가
얇은 직군**이었다:

    data_analyst  신입가능   2 / 전체    4      <- 검색으로 못 고친다
    sre           신입가능  10 / 전체   31
    data_scientist 신입가능 11 / 전체   43
    (대조) backend 신입가능 787 / 전체 1681

재고가 없는 것은 랭킹 개선으로 해결되지 않는다. 목표 직무에 맞는 공고가 없다는
사실을 감추지 않고, **본인 기술을 쓸 수 있는 인접/하위 자리**를 제안하는 것이
이 모듈의 역할이다.

용어 주의 — "하위"가 아니라 "진입 경로"인 경우가 있다
--------------------------------------------------
셰프 → 주방보조처럼 명확한 상하 관계가 IT에는 드물다. 실제로는 두 종류가 섞인다.

  · **하위(downward)**  : sre -> devops -> backend 처럼 요구 수준이 낮아지는 방향
  · **측면(lateral)**   : data_analyst -> data_engineer 처럼 난이도는 비슷하거나
                          오히려 높지만 **일자리가 있는 쪽**으로 옮기는 방향

data_analyst가 대표적이다. 데이터 분석가는 이미 진입 직군이라 더 낮은 단계가 없다.
문제는 난이도가 아니라 재고(2건)이므로 사다리가 **측면**이 된다. 이걸 "하위직무"라고
사용자에게 표시하면 거짓말이 되므로 `direction` 필드로 구분해 문구를 바꾼다.

연차 축은 이미 있다
-------------------
`seniority.py`가 intern < junior < mid < senior를 제공한다. 디딤돌 검색은
직군을 사다리로 바꾸는 동시에 **junior·intern을 우선**한다. 즉 두 축을 함께 내린다.
"""
from __future__ import annotations

# ── 트리거 임계값 ──────────────────────────────────────
#
# "목표 직군의 신입 가능 공고가 이보다 적으면 재고 부족으로 본다."
# 임계값에 따라 대상 직군과 실패 커버리지가 이렇게 바뀐다(2026-07-30 실측):
#
#   < 10건 : data_analyst                                    -> 완전실패 7건 중 4건
#   < 20건 : + data_scientist, sre                            -> 6건   ← 채택
#   < 40건 : + qa                                             -> 7건
#   < 70건 : + frontend, devops, data_engineer, ml_engineer    -> 7건
#
# 20을 택한 이유: 40으로 올리면 qa(33건)가 들어와 실패 1건을 더 잡지만, 재고가
# 33건이나 있는 직군을 "재고 부족"이라 부르는 건 무리다. 발동하면 postings를
# 비우므로 **오발동 비용이 크다** — 좁게 잡는 쪽이 안전하다.
# 이 값은 코퍼스가 커지면 재조정해야 한다(절대 건수 기준이므로).
SCARCE_JUNIOR_THRESHOLD = 20

# 트리거 보조 조건 — 상위 3건의 평균 기술 교집합이 이보다 낮아야 발동.
# 근거: 교집합 3+ 는 Correct 63.1%, 교집합 0 은 47.6%로 신호가 약해진다(실측).
MIN_TECH_OVERLAP = 2

# ── 사다리 ─────────────────────────────────────────────
# steps  : 가까운 순서. 앞쪽을 먼저 제안한다.
# direction: "downward"(요구 수준이 낮아짐) | "lateral"(난이도 비슷, 일자리 있는 쪽)
# basis  : "문서" = eval/JUDGING_CRITERIA.md 등 근거 있음 / "판단" = 저자 판단
LADDER: dict[str, dict] = {
    "sre": {
        "steps": ["devops", "backend"],
        "direction": "downward",
        "basis": "문서",
        "why": ("JUDGING_CRITERIA §3-1이 SRE↔DevOps를 인접(Ambiguous)으로 명시한다. "
                "SRE는 통상 운영 경력을 요구하므로 DevOps -> backend 순으로 낮아진다."),
    },
    "data_scientist": {
        "steps": ["data_analyst", "data_engineer"],
        "direction": "downward",
        "basis": "판단",
        "why": ("분석 실무(data_analyst)가 선행 경험으로 통용된다는 저자 판단. "
                "단 data_analyst 자체가 재고 2건이므로 실효는 data_engineer에 달렸다."),
    },
    "data_analyst": {
        "steps": ["data_engineer", "backend"],
        "direction": "lateral",
        "basis": "판단",
        "why": ("데이터 분석가는 이미 진입 직군이라 더 낮은 단계가 없다. 재고가 2건뿐인 "
                "것이 문제이므로 SQL·Python이 쓰이는 인접 직군으로 **측면 이동**을 제안한다. "
                "난이도가 낮아지는 것이 아니므로 사용자에게 '하위 직무'로 표시하면 안 된다."),
    },
    "ml_engineer": {
        "steps": ["data_engineer", "data_analyst"],
        "direction": "downward",
        "basis": "판단",
        "why": ("모델 서빙·파이프라인 경험이 선행된다는 저자 판단. "
                "JUDGING_CRITERIA §3-1은 인접 데이터 직군을 '구분한다'고만 하고 "
                "진입 순서는 규정하지 않는다 — 그 부분이 판단이다."),
    },
    "devops": {
        "steps": ["backend"],
        "direction": "downward",
        "basis": "판단",
        "why": "서버 개발 경험이 인프라 운영의 선행 경험으로 통용된다는 저자 판단.",
    },
    "security": {
        "steps": ["devops", "backend"],
        "direction": "downward",
        "basis": "판단",
        "why": ("보안 직군 진입이 인프라·서버 경험을 경유한다는 저자 판단. "
                "보안은 재고 283건으로 충분해 실제로는 트리거되지 않을 것이다."),
    },
    "qa": {
        "steps": ["backend", "frontend"],
        "direction": "lateral",
        "basis": "판단",
        "why": ("QA도 진입 직군이라 하위가 없다. 재고 33건으로 임계값 20을 넘어 "
                "**현 설정에서는 트리거되지 않는다** — 임계를 40으로 올릴 때만 쓰인다."),
    },
    "fullstack": {
        "steps": ["backend", "frontend"],
        "direction": "downward",
        "basis": "문서",
        "why": ("JUDGING_CRITERIA §3이 풀스택↔백엔드/프론트엔드를 Correct로 인정한다. "
                "범위가 좁아지는 방향이므로 하위로 본다. 재고 566건이라 트리거 안 됨."),
    },
    # 아래 세 직군은 사다리를 두지 않는다.
    # 이미 진입 직군이고 재고가 충분해(frontend 65 / mobile 157 / backend 787)
    # 트리거 조건 3(<20)을 통과할 수 없다. 억지로 사다리를 만들면
    # "backend 지망에게 무엇을 권하겠는가"라는 답 없는 질문에 답해야 한다.
    "backend": {"steps": [], "direction": "none", "basis": "판단",
                "why": "진입 직군이며 재고 787건. 디딤돌 대상이 아니다."},
    "frontend": {"steps": [], "direction": "none", "basis": "판단",
                 "why": "진입 직군이며 재고 65건. 디딤돌 대상이 아니다."},
    "mobile": {"steps": [], "direction": "none", "basis": "판단",
               "why": "진입 직군이며 재고 157건. 디딤돌 대상이 아니다."},
    "data_engineer": {"steps": ["backend"], "direction": "downward", "basis": "판단",
                      "why": "재고 66건으로 트리거 밖. 만일을 위해 backend만 둔다."},
}

DIRECTION_LABEL = {
    "downward": "하위 직무",
    "lateral": "인접 직무 (난이도가 낮아지는 것은 아님)",
    "none": "—",
}


def steps_for(role_category: str | None) -> list[str]:
    """목표 직군의 디딤돌 후보를 가까운 순으로. 없으면 빈 리스트."""
    if not role_category:
        return []
    return list(LADDER.get(role_category, {}).get("steps", []))


def direction_of(role_category: str | None) -> str:
    return LADDER.get(role_category or "", {}).get("direction", "none")


def explain(target: str, offered: str) -> str:
    """사용자에게 보여줄 한 줄. `direction`에 따라 문구가 달라진다 —
    측면 이동을 '하위 직무'라고 쓰면 거짓 표시가 된다."""
    d = direction_of(target)
    if d == "lateral":
        return (f"{target} 공고가 코퍼스에 매우 적습니다. 보유 기술을 활용할 수 있는 "
                f"인접 직무 {offered} 자리를 제안합니다(난이도가 낮아지는 것은 아닙니다).")
    if d == "downward":
        return (f"{target} 조건에 맞는 공고를 찾지 못했습니다. 선행 경험을 쌓을 수 있는 "
                f"{offered} 자리를 제안합니다.")
    return f"{offered} 자리를 제안합니다."


def audit() -> list[dict]:
    """사다리 전체를 표로 — 도메인 검토용. 근거 등급을 함께 낸다."""
    return [{"target": k, "steps": v["steps"], "direction": v["direction"],
             "basis": v["basis"], "why": v["why"]} for k, v in LADDER.items()]


if __name__ == "__main__":
    from .store import connect
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""SELECT role_category,
                          count(*) FILTER (WHERE exp_min = 0 OR exp_min IS NULL),
                          count(*)
                       FROM postings WHERE is_active AND role_category <> ''
                       GROUP BY 1""")
        inv = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    conn.close()

    print(f"디딤돌 사다리 검토표  (트리거 임계 신입가능 < {SCARCE_JUNIOR_THRESHOLD}건)\n")
    print(f"{'목표':16} {'신입/전체':>11} {'발동':>5} {'근거':>5} {'방향':>6}  디딤돌")
    for row in audit():
        j, t = inv.get(row["target"], (0, 0))
        fire = "예" if j < SCARCE_JUNIOR_THRESHOLD else "아니오"
        # 디딤돌 후보의 재고도 함께 보여준다 — 사다리가 실효 있는지 판단하려면 필요하다
        st = " → ".join(f"{s}({inv.get(s, (0, 0))[0]})" for s in row["steps"]) or "—"
        print(f"{row['target']:16} {j:>5}/{t:<5} {fire:>5} {row['basis']:>5} "
              f"{row['direction']:>9}  {st}")
    print("\n근거 '판단' 항목은 측정으로 뒷받침되지 않은 저자 도메인 판단이다.")
    print("괄호 안 숫자는 그 디딤돌 직군의 신입 가능 공고 수 — 0이면 사다리가 무의미하다.")
