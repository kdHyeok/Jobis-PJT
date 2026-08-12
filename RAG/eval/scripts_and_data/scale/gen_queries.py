# -*- coding: utf-8 -*-
"""대량 질의 생성기 — 직군 x 기술 x 지역 x 경력 조합으로 400개 질의 생성.

golden/queries.py의 65개(수작업 큐레이션)에 프로그래매틱 조합을 더해
총 규모를 수백 단위로 확장한다. 결정적 생성이라 재현 가능.
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, r"c:\Users\SSAFY\Desktop\rag-pipeline\S15P11C202\RAG")
sys.stdout.reconfigure(encoding="utf-8")

random.seed(42)

ROLES = [
    ("백엔드 개발자", ["Java", "Spring Boot", "Python", "Django", "Go", "Node.js", "PHP", "Kotlin"]),
    ("프론트엔드 개발자", ["React", "Vue", "TypeScript", "Next.js", "JavaScript"]),
    ("풀스택 개발자", ["React", "Node.js", "Spring Boot", "TypeScript"]),
    ("안드로이드 개발자", ["Kotlin", "Java", "Android"]),
    ("iOS 개발자", ["Swift", "iOS"]),
    ("데이터 엔지니어", ["Python", "Spark", "Kafka", "Airflow", "SQL"]),
    ("데이터 사이언티스트", ["Python", "TensorFlow", "PyTorch", "SQL"]),
    ("머신러닝 엔지니어", ["Python", "PyTorch", "LLM", "TensorFlow"]),
    ("데이터 분석가", ["SQL", "Python", "Tableau"]),
    ("DevOps 엔지니어", ["Docker", "Kubernetes", "AWS", "Jenkins", "Terraform"]),
    ("SRE 엔지니어", ["Kubernetes", "Linux", "Terraform", "AWS"]),
    ("QA 엔지니어", ["Python", "Selenium", "Git"]),
    ("보안 엔지니어", ["Linux", "AWS", "네트워크"]),
    ("클라우드 엔지니어", ["AWS", "Azure", "GCP", "Kubernetes"]),
    ("게임 클라이언트 개발자", ["Unity", "C++", "C#"]),
    ("임베디드 개발자", ["C", "C++", "Linux"]),
]

REGIONS = ["서울", "경기", "인천", "부산", "대구", "대전", "광주", None]
EXP = ["신입", "1년차", "2년차", "3년차", "5년차", "7년차", "경력무관", None]

TEMPLATES = [
    "{region} {exp} {tech} {role}",
    "{region} {exp} {tech} 쓰는 {role} 채용",
    "{exp} {role} ({tech})",
    "{tech} 다루는 {role} 구합니다 {region}",
    "{region} {role} {tech} 경험자",
    "{tech} {role} {exp}",
]

CATEGORY = "programmatic_combo"


def build_query(role, tech, region, exp, template):
    parts = {
        "role": role,
        "tech": tech,
        "region": region or "",
        "exp": exp or "",
    }
    text = template.format(**parts)
    text = " ".join(text.split())  # 중복 공백 정리
    return text


def generate(n_target=400):
    combos = []
    for role, techs in ROLES:
        for tech in techs:
            for region in REGIONS:
                for exp in EXP:
                    combos.append((role, tech, region, exp))
    random.shuffle(combos)

    seen = set()
    out = []
    i = 0
    for role, tech, region, exp in combos:
        if len(out) >= n_target:
            break
        template = random.choice(TEMPLATES)
        text = build_query(role, tech, region, exp, template)
        if text in seen:
            continue
        seen.add(text)
        i += 1
        out.append({"id": f"pq{i:04d}", "text": text, "category": CATEGORY,
                    "role": role, "tech": tech, "region": region, "exp": exp})
    return out


def main():
    from golden.queries import QUERIES as GOLDEN

    golden = [{"id": q["id"], "text": q["text"], "category": q["category"],
               "role": None, "tech": None, "region": None, "exp": None} for q in GOLDEN]
    combo = generate(n_target=400 - len(golden))
    all_q = golden + combo
    outpath = Path(__file__).parent / "queries_large.json"
    outpath.write_text(json.dumps(all_q, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"총 {len(all_q)}개 질의 생성 (골든 {len(golden)} + 조합생성 {len(combo)}) -> {outpath}")


if __name__ == "__main__":
    main()
