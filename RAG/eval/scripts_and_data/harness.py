# -*- coding: utf-8 -*-
"""RAG 환각 결정적 검출 하네스 (LLM 불필요)

3층 평가:
  1층 검색 오류: retrieved_context_ids vs reference_context_ids (누락/오검색)
  2층 생성 환각: 답변이 검색 컨텍스트에 없는 회사를 추천(fabrication),
               또는 회사 조건(기술)을 왜곡(attribute distortion)
  3층 답변 정확성: 답변 추천 회사 vs reference 정답 회사 (답변누락/오답)
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
DATASET = Path(r"c:\Users\SSAFY\Desktop\rag-pipeline\S15P11C202\RAG\eval\ragas_dataset.json")

# generate.py의 SYSTEM_PROMPT 그대로
SYSTEM_PROMPT = """당신은 채용공고 검색 어시스턴트입니다.
아래 [검색결과]만 근거로 사용자 질문에 답하세요.
- 검색결과에 없는 공고를 지어내지 마세요.
- 각 추천에는 회사명과 핵심 조건(경력/지역/기술)을 포함하세요.
- 조건에 정확히 맞는 게 없으면 그렇다고 말하고 가장 가까운 대안을 제시하세요.
- 한국어로, 간결하게 답하세요."""


def norm_company(name: str) -> str:
    s = unicodedata.normalize("NFKC", name)
    s = re.sub(r"[㈜(（]\s*주\s*[)）]|㈜|\(주\)|주식회사", "", s)
    s = re.sub(r"[\s·.\-_/\[\]()（）]", "", s)
    return s.lower()


def parse_context(ctx: str) -> dict:
    """컨텍스트 프리픽스에서 회사/핵심조건 추출."""
    company = ""
    m = re.search(r"\[회사\]\s*(.+)", ctx)
    if m:
        company = m.group(1).strip()
    techs = []
    regions = []
    exp = None
    m = re.search(r"\[핵심조건\]\s*(.+)", ctx)
    if m:
        cond = m.group(1)
        parts = [p.strip() for p in cond.split("·")]
        for p in parts:
            if p.startswith("기술:"):
                for t in p[3:].split(","):
                    t = t.strip()
                    # "Spring Boot(스프링부트)" -> 표준명 + 별칭 모두 등록
                    mm = re.match(r"([^()]+)(?:\(([^)]+)\))?", t)
                    if mm:
                        techs.append(mm.group(1).strip())
                        if mm.group(2):
                            techs.append(mm.group(2).strip())
            elif "경력" in p:
                exp = p
            elif re.search(r"(서울|경기|인천|부산|대구|대전|광주|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주)", p):
                regions.append(p)
    return {"company": company, "company_norm": norm_company(company),
            "techs": techs, "techs_norm": {norm_tech(t) for t in techs},
            "regions": regions, "exp": exp}


def norm_tech(t: str) -> str:
    return re.sub(r"[\s.\-_]", "", t).lower()


# 자주 쓰이는 별칭(화이트리스트 축약판) — 답변에 표준/별칭 어느 쪽이 나와도 매칭
ALIAS = {
    "스프링부트": "springboot", "spring boot": "springboot",
    "자바": "java", "파이썬": "python", "리액트": "react", "코틀린": "kotlin",
    "장고": "django", "노드": "nodejs", "node.js": "nodejs", "타입스크립트": "typescript",
    "자바스크립트": "javascript", "쿠버네티스": "kubernetes", "도커": "docker",
    "젠킨스": "jenkins", "오라클": "oracle", "하이버네이트": "jpa", "마이바티스": "mybatis",
    "안드로이드": "android", "텐서플로": "tensorflow", "파이토치": "pytorch",
    "깃랩": "gitlab", "깃": "git", "리눅스": "linux", "테라폼": "terraform",
    "카프카": "kafka", "레디스": "redis",
}


def canon_tech(t: str) -> str:
    n = norm_tech(t)
    return norm_tech(ALIAS.get(t.strip().lower(), ALIAS.get(n, n)))


# 답변에서 스캔할 기술 토큰 후보(컨텍스트 기술 + 흔한 기술명)
TECH_SCAN = [
    "Spring Boot", "스프링부트", "Spring", "JPA", "MyBatis", "MySQL", "MariaDB",
    "PostgreSQL", "Oracle", "오라클", "Redis", "Kafka", "카프카", "Docker", "도커",
    "Kubernetes", "쿠버네티스", "Jenkins", "젠킨스", "AWS", "Azure", "GCP",
    "Java", "자바", "Python", "파이썬", "Go", "Kotlin", "코틀린", "Swift",
    "React", "리액트", "Vue", "Next.js", "Node.js", "노드", "TypeScript",
    "JavaScript", "Django", "장고", "Flask", "FastAPI", "TensorFlow", "PyTorch",
    "Terraform", "테라폼", "Linux", "리눅스", "Git", "GitLab", "Android", "안드로이드",
    "LLM", "Elasticsearch", "GraphQL", "C++", "C#", "Ruby", "Rust", "Scala", "Hadoop", "Spark",
]


def _company_in(cnorm: str, text_norm: str) -> bool:
    """회사명이 텍스트에 등장하는가 — 접미사 생략('...인크' 등)도 허용."""
    if not cnorm:
        return False
    if cnorm in text_norm:
        return True
    # 답변이 회사명 뒷부분을 줄여 쓴 경우: 앞 4자 이상 일치하는 프리픽스가 텍스트에 있으면 매칭
    for cut in range(len(cnorm) - 1, 3, -1):
        if cnorm[:cut] in text_norm:
            return True
    return False


def _match_company(text: str, known: list[dict]):
    tn = norm_company(text)
    for k in known:
        if _company_in(k["company_norm"], tn):
            return k
    return None


def extract_recommendations(answer: str, known: list[dict]) -> list[dict]:
    """추천 블록 추출: 제목 라인(번호/볼드) + 그 아래 속성 불릿을 한 블록으로.

    제목으로 인정하는 라인:
      - "1. ..." / "1) ..." 번호 매김
      - "**...**" 볼드 (단, ':'로 끝나는 섹션 제목 제외)
    제목에 컨텍스트 회사가 없으면 fabrication.
    속성 불릿("- 기술: ...")은 직전 제목 블록에 붙여 왜곡 검사에 사용.
    """
    recs = []
    cur = None
    for raw in answer.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_numbered = bool(re.match(r"^\d+[.)]\s+", line))
        is_bold = "**" in line and not line.rstrip("*").rstrip().endswith(":")
        is_attr = bool(re.match(r"^[-*•]\s*\S[^:]{0,20}:", line))
        if is_numbered or (is_bold and not is_attr):
            # 회사-직무 제목처럼 보일 때만 추천 항목으로 취급
            has_sep = bool(re.search(r"\s[-–]\s|—", line)) or is_numbered
            matched = _match_company(line, known)
            if matched is None and not has_sep:
                continue  # 단순 강조 문장 — 추천 아님
            cur = {"line": line, "matched": matched, "block": line}
            recs.append(cur)
        elif is_attr and cur is not None:
            cur["block"] += "\n" + line
    return recs


def check_answer(answer: str, contexts: list[str]) -> dict:
    """2층: grounding 검사."""
    known = [parse_context(c) for c in contexts]
    recs = extract_recommendations(answer, known)
    fabrications = [r["line"] for r in recs if r["matched"] is None]
    distortions = []
    for r in recs:
        k = r["matched"]
        if k is None:
            continue
        # 라인에 언급된 기술이 해당 회사의 '모든' 컨텍스트(같은 회사 공고 여러 건 가능)
        # 어디에도 없을 때만 왜곡으로 판정
        same = [c for c in contexts if parse_context(c)["company_norm"] == k["company_norm"]]
        ctx_norm = norm_tech("\n".join(same))
        k_techs = set()
        for c in same:
            k_techs |= parse_context(c)["techs_norm"]
        claimed = set()
        for t in TECH_SCAN:
            if re.search(re.escape(t), r["block"], re.IGNORECASE):
                claimed.add(t)
        for t in claimed:
            if canon_tech(t) not in {canon_tech(x) for x in k_techs} \
               and canon_tech(t) not in ctx_norm:
                distortions.append({"company": k["company"], "tech": t, "line": r["line"]})
    return {
        "n_recs": len(recs),
        "n_grounded": sum(1 for r in recs if r["matched"] is not None),
        "fabrications": fabrications,
        "distortions": distortions,
    }


def check_reference(answer: str, sample: dict) -> dict:
    """3층: 답변 추천 vs reference 정답 회사."""
    ref_companies = []
    for line in sample["reference"].splitlines():
        m = re.match(r"^-\s*(.+?)\s*-\s", line.strip())
        if m:
            ref_companies.append(m.group(1).strip())
    ref_norm = {norm_company(c) for c in ref_companies}
    ret_companies = [parse_context(c)["company"] for c in sample["retrieved_contexts"]]
    ans_norm = norm_company(answer)
    mentioned = {norm_company(c) for c in ret_companies if norm_company(c) in ans_norm}
    correct = mentioned & ref_norm
    wrong = mentioned - ref_norm  # 검색됐지만 정답 아닌 걸 추천
    # 검색됐고 정답인데 답변에서 빠뜨림
    retrievable_ref = {norm_company(c) for c in ret_companies} & ref_norm
    omitted = retrievable_ref - mentioned
    return {"recommended_correct": len(correct), "recommended_wrong": len(wrong),
            "answer_omitted": len(omitted)}


def check_retrieval(sample: dict) -> dict:
    """1층: 검색 자체의 누락/정밀도."""
    ret = set(sample["retrieved_context_ids"])
    ref = set(sample["reference_context_ids"])
    hit = ret & ref
    cap = min(len(ret), len(ref))  # k=3 저장 데이터의 recall 상한 보정
    return {
        "retrieved": len(ret), "reference": len(ref), "hit": len(hit),
        "precision": round(len(hit) / len(ret), 3) if ret else None,
        "recall": round(len(hit) / cap, 3) if cap else None,  # capped recall@k
    }


def load_samples():
    return json.load(open(DATASET, encoding="utf-8"))["samples"]


def cmd_build_inputs():
    """Haiku 에이전트용 생성 프롬프트 파일 작성."""
    outdir = HERE / "inputs"
    outdir.mkdir(exist_ok=True)
    (HERE / "outputs").mkdir(exist_ok=True)
    for s in load_samples():
        ctx_lines = []
        for i, c in enumerate(s["retrieved_contexts"], 1):
            ctx_lines.append(f"{i}. {c}")
        prompt = (
            f"{SYSTEM_PROMPT}\n\n[검색결과]\n" + "\n\n".join(ctx_lines)
            + f"\n\n[사용자 질문]\n{s['question']}\n"
        )
        (outdir / f"{s['qid']}.txt").write_text(prompt, encoding="utf-8")
    print(f"built {len(load_samples())} input files -> {outdir}")


def evaluate(answers: dict[str, str], label: str):
    """answers: qid -> answer text"""
    rows = []
    for s in load_samples():
        qid = s["qid"]
        if qid not in answers:
            continue
        a = answers[qid]
        g = check_answer(a, s["retrieved_contexts"])
        r3 = check_reference(a, s)
        r1 = check_retrieval(s)
        rows.append({"qid": qid, **{f"g_{k}": v for k, v in g.items()},
                     **{f"a_{k}": v for k, v in r3.items()},
                     **{f"r_{k}": v for k, v in r1.items()}})
    n = len(rows)
    fab = sum(1 for r in rows if r["g_fabrications"])
    dis = sum(1 for r in rows if r["g_distortions"])
    print(f"\n===== [{label}] {n} samples =====")
    print(f"허위 공고(fabrication) 포함 답변: {fab}/{n}")
    print(f"조건 왜곡(distortion) 포함 답변: {dis}/{n}")
    tot_recs = sum(r["g_n_recs"] for r in rows)
    tot_ground = sum(r["g_n_grounded"] for r in rows)
    print(f"추천 항목 grounding: {tot_ground}/{tot_recs}")
    print(f"답변누락(검색된 정답을 빠뜨림) 합계: {sum(r['a_answer_omitted'] for r in rows)}")
    print(f"오답 추천(정답 아닌 공고 추천) 합계: {sum(r['a_recommended_wrong'] for r in rows)}")
    recalls = [r["r_recall"] for r in rows if r["r_recall"] is not None]
    precs = [r["r_precision"] for r in rows if r["r_precision"] is not None]
    print(f"[검색] 평균 recall: {sum(recalls)/len(recalls):.3f}, 평균 precision: {sum(precs)/len(precs):.3f}")
    for r in rows:
        if r["g_fabrications"] or r["g_distortions"]:
            print(f"  ! {r['qid']}: fab={r['g_fabrications']} dist={[(d['company'],d['tech']) for d in r['g_distortions']]}")
    return rows


def cmd_eval_stored():
    samples = load_samples()
    answers = {s["qid"]: s["response"] for s in samples}
    evaluate(answers, "기존 저장 응답(template)")


def cmd_eval_generated():
    outdir = HERE / "outputs"
    answers = {}
    for f in sorted(outdir.glob("SA*.txt")):
        answers[f.stem] = f.read_text(encoding="utf-8")
    evaluate(answers, f"Haiku 생성 응답 ({len(answers)}건)")


def cmd_mutation():
    """검출기 자체 검증: 환각을 주입하고 잡아내는지 확인."""
    s = load_samples()[0]  # SA01
    base = s["response"]
    ctxs = s["retrieved_contexts"]
    cases = [
        ("허위회사-1", base + "\n4. ㈜가짜테크 - 백엔드 개발자 채용 (주요 기술: Java, Spring Boot)", "fab"),
        ("허위회사-2", base + "\n4. 클라우드나인소프트 - 서버 개발자 모집 (주요 기술: Kotlin)", "fab"),
        ("허위회사-3", base.replace("마이데이터", "네이버클라우드"), "fab"),
        ("기술왜곡-1", base.replace("㈜누리인포스 - 백엔드 개발자 (5년이상) 모집 (주요 기술: Spring Boot",
                                   "㈜누리인포스 - 백엔드 개발자 (5년이상) 모집 (주요 기술: Django"), "dist"),
        ("기술왜곡-2", base.replace("마이데이터 - Java, Spring Boot 백엔드 개발자 모집 (주요 기술: Spring Boot, MyBatis",
                                   "마이데이터 - Java, Spring Boot 백엔드 개발자 모집 (주요 기술: React, PostgreSQL"), "dist"),
        ("기술왜곡-3", base.replace("(주요 기술: Spring Boot, Kubernetes, JPA, Docker, MySQL)",
                                   "(주요 기술: Spring Boot, Rust, Elasticsearch)"), "dist"),
        ("정상-1(원본)", base, "clean"),
        ("정상-2(별칭표기)", base.replace("Spring Boot", "스프링부트").replace("Java", "자바"), "clean"),
        ("정상-3(㈜생략)", base.replace("㈜누리인포스", "누리인포스").replace("㈜메가젠임플란트", "메가젠임플란트"), "clean"),
    ]
    print("\n===== 변이 주입 테스트 (검출기 검증) =====")
    ok = 0
    for name, ans, expect in cases:
        g = check_answer(ans, ctxs)
        got_fab = bool(g["fabrications"])
        got_dist = bool(g["distortions"])
        if expect == "fab":
            passed = got_fab
        elif expect == "dist":
            passed = got_dist
        else:
            passed = not got_fab and not got_dist
        ok += passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: fab={got_fab} dist={got_dist} (기대={expect})")
        if not passed:
            print(f"        detail: {g}")
    print(f"검출기 검증: {ok}/{len(cases)} 통과")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "build":
        cmd_build_inputs()
    elif cmd == "stored":
        cmd_eval_stored()
    elif cmd == "generated":
        cmd_eval_generated()
    elif cmd == "mutation":
        cmd_mutation()
    else:
        cmd_build_inputs()
        cmd_eval_stored()
        cmd_mutation()
