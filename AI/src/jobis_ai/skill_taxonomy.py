"""스킬 taxonomy (skill_taxonomy) — 기술명 표준화·동의어 흡수·카테고리 분류.

공고와 이력서는 같은 기술을 다르게 적는다("ReactJS" / "React.js" / "리액트").
표준 키로 모으지 않으면 `gap_matcher` 의 1차 정확 매칭이 전부 빗나간다.
이 모듈이 그 표준화를 담당한다. (설계: agent-derivation-and-tools.md §3.1, §3.2, §3.5)

역할 경계:
- **순수 내부 정형 DB + 룰**이다. LLM/RAG/임베딩을 쓰지 않는다 — 동의어 매핑은 결정론이어야 한다.
- "이 사람이 이 스킬을 갖췄나"는 판정하지 않는다. 여기는 **이름을 표준형으로 바꾸는 일**만 한다.

한계(의도적):
- `find_in_text` 는 2글자 이하 **ASCII** 별칭(C, R, Go)을 건너뛴다. 짧은 영문 토큰은 일반
  산문에서 오탐이 너무 많다("Go to the ..."). 대신 `Golang`, `C언어` 같은 긴 별칭을 두고,
  놓친 것은 파서의 2차 LLM 추출이 잡는다(§3.1 하이브리드).
- 한글 별칭은 2글자부터 허용한다. "도커"·"자바"는 2글자여도 그 자체로 완결된 단어라
  오탐 위험이 없다. ASCII 기준을 그대로 적용하면 흔한 한글 표기를 통째로 놓친다.

스캐폴딩 단계: 시드는 대표 IT 스킬만 담았다. 운영 시 `_SKILLS` 를 확장하거나 외부 DB
로드로 교체하되, `SkillTaxonomy` 의 공개 메서드 시그니처는 유지한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from jobis_ai.embed import get_embedder

# 사전에 없는 표기의 임베딩 유사도 매칭 임계값. gap_matcher 의 _EMBED_MET(0.75)보다
# 높게 잡는다 — 여기서는 "관련 있음"이 아니라 "동일한 스킬"이라고 단정하는 것이라
# 더 엄격해야 한다(React~Vue 처럼 관련은 있지만 다른 것까지 합치면 안 된다).
_EMBED_SKILL_MATCH = 0.85

# 스킬 카테고리 — gap_matcher 의 scoreBasis 집계(§3.5)가 이 값으로 가중치를 나눈다.
SkillCategory = str  # "language" | "framework" | "database" | "cloud" | "devops" | "data" | "testing" | "etc"

# find_in_text 가 요구하는 최소 별칭 길이 (오탐 방지). 위 '한계' 주석 참고.
_MIN_ASCII_ALIAS = 3   # "Go", "C" 등 짧은 영문은 산문에서 오탐이 많다
_MIN_HANGUL_ALIAS = 2  # "도커", "자바"는 2글자여도 완결된 단어다

_HANGUL = re.compile(r"[가-힣]")

# 표기 정규화에서 무시하는 구분자: 점·공백·하이픈·언더스코어.
# "React.js" == "React js" == "React-js" == "ReactJS" 를 같은 키로 모은다.
# '+'·'#' 은 일부러 제외한다 — C++·C# 처럼 이름의 일부라, 지우면 서로 다른 언어가 뭉개진다.
_SEPARATORS = re.compile(r"[.\s\-_]+")


def _normalize_key(text: str) -> str:
    """별칭/입력을 조회용 표준 키로. 소문자화 + 구분자(., 공백, -, _) 제거.

    대소문자·띄어쓰기·점·하이픈 차이는 여기서 흡수한다. 그래서 같은 글자 구성의
    표기 변형("Node.js"/"Node js"/"NodeJS")을 aliases 에 일일이 나열할 필요가 없다 —
    글자 구성 자체가 다른 표기(리액트/React, SpringBoot/스프링부트)만 등록하면 된다.
    """

    return _SEPARATORS.sub("", (text or "").strip().lower())


def _is_searchable(alias: str) -> bool:
    """원문 검색에 쓸 수 있을 만큼 변별력 있는 별칭인지."""

    minimum = _MIN_HANGUL_ALIAS if _HANGUL.search(alias) else _MIN_ASCII_ALIAS
    return len(alias) >= minimum


@dataclass(frozen=True)
class Skill:
    """표준 스킬 1건.

    key       : 내부 표준 키(소문자 슬러그). 매칭·매핑의 기준값.
    canonical : 사람이 읽는 표시명. 최종 산출물에 나가는 이름.
    category  : scoreBasis 집계 단위.
    aliases   : 원문에서 이 스킬을 가리킬 수 있는 표기들(canonical 은 자동 포함).
    implies   : 이 스킬을 쓴다면 **반드시 함께 쓰는** 상위/포함 스킬의 key 들.

    `implies` 와 `aliases` 의 차이(헷갈리면 판정이 망가진다):
    - aliases  = 같은 것의 다른 이름. "ReactJS" == "React".
    - implies  = 다른 것이지만 논리적으로 수반됨. MySQL 을 썼다면 RDBMS 와 SQL 을 쓴 것이다.
    implies 가 없으면 "MySQL 등 RDBMS 설계 및 SQL 활용" 요구사항에서 RDBMS·SQL 을 각각
    따로 증명하라고 요구하게 되어, MySQL 경험자가 미충족으로 찍힌다.

    **엄격히 수반되는 것만 넣는다.** 예: "Spring Boot → Java" 는 넣지 않는다 —
    Spring Boot 는 Kotlin 으로도 쓴다. 애매하면 넣지 않는 쪽이 안전하다.
    """

    key: str
    canonical: str
    category: SkillCategory
    aliases: tuple[str, ...] = ()
    implies: tuple[str, ...] = ()


_SKILLS: tuple[Skill, ...] = (
    # --- 언어 ---
    Skill("java", "Java", "language", ("자바",)),
    Skill("kotlin", "Kotlin", "language", ("코틀린",)),
    Skill("python", "Python", "language", ("파이썬",)),
    Skill("javascript", "JavaScript", "language", ("자바스크립트", "JS", "ES6", "ECMAScript")),
    Skill("typescript", "TypeScript", "language", ("타입스크립트", "TS")),
    Skill("go", "Go", "language", ("Golang", "고랭")),
    Skill("c", "C", "language", ("C 언어",)),
    Skill("cpp", "C++", "language", ("씨쁠쁠", "CPP")),
    Skill("csharp", "C#", "language", ("씨샵",)),
    Skill("rust", "Rust", "language", ("러스트",)),
    Skill("php", "PHP", "language", ()),
    Skill("ruby", "Ruby", "language", ("루비",)),
    Skill("swift", "Swift", "language", ("스위프트",)),
    Skill("dart", "Dart", "language", ("다트",)),
    Skill("objective-c", "Objective-C", "language", ("오브젝티브C", "ObjC")),
    Skill("html", "HTML", "language", ("HTML5",)),
    Skill("css", "CSS", "language", ("CSS3",)),
    # Sass 는 CSS 전처리기 — CSS 의 별칭이 아니라 별도 도구다.
    Skill("sass", "Sass", "language", ("SCSS",), implies=("css",)),
    Skill("bash", "Bash", "language", ("쉘 스크립트", "Shell Script", "셸 스크립트")),
    Skill("matlab", "MATLAB", "language", ("매트랩",)),
    Skill("solidity", "Solidity", "language", ("솔리디티",)),
    Skill("scala", "Scala", "language", ("스칼라",)),
    Skill("sql", "SQL", "language", ("에스큐엘",)),

    # --- 프레임워크/라이브러리 ---
    Skill("spring", "Spring", "framework", ("스프링", "Spring Framework")),
    # Spring Boot → Spring 만 함의한다. Java 는 함의하지 않는다(Kotlin 으로도 쓴다).
    Skill("spring-boot", "Spring Boot", "framework", ("스프링 부트",),
          implies=("spring",)),
    Skill("jpa", "JPA", "framework", ("Hibernate", "하이버네이트", "Spring Data JPA")),
    Skill("mybatis", "MyBatis", "framework", ("마이바티스",)),
    # 구분자·대소문자 변형("NodeJS"/"Node.JS"/"노드js")은 _normalize_key 와 _flexible 이
    # 흡수하므로 별칭에 안 적는다. 글자 구성이 다른 표기(한글)만 대표형 하나로 남긴다.
    Skill("node", "Node.js", "framework", ("노드 js",)),
    Skill("express", "Express", "framework", ("Express.js",), implies=("node",)),
    Skill("nestjs", "NestJS", "framework", ("Nest.js", "네스트js"), implies=("node",)),
    Skill("django", "Django", "framework", ("장고",)),
    Skill("fastapi", "FastAPI", "framework", ("Fast API",)),
    Skill("flask", "Flask", "framework", ("플라스크",)),
    Skill("react", "React", "framework", ("React.js", "리액트")),
    Skill("nextjs", "Next.js", "framework", ("NextJS", "넥스트js"), implies=("react",)),
    Skill("vue", "Vue.js", "framework", ("VueJS", "Vue", "뷰js")),
    Skill("angular", "Angular", "framework", ("AngularJS", "앵귤러")),
    Skill("svelte", "Svelte", "framework", ("스벨트",)),
    # 모바일 — 0724 파싱 A/B 실험에서 커버리지 공백으로 확인돼 추가 (작업로그 0724 §7)
    Skill("flutter", "Flutter", "framework", ("플러터",), implies=("dart",)),
    Skill("react-native", "React Native", "framework", ("리액트 네이티브",), implies=("react",)),
    Skill("swiftui", "SwiftUI", "framework", ("스위프트UI",), implies=("swift",)),
    Skill("jetpack-compose", "Jetpack Compose", "framework", ("젯팩 컴포즈", "컴포즈"),
          implies=("kotlin",)),
    Skill("spring-security", "Spring Security", "framework", ("스프링 시큐리티",)),
    Skill("langchain", "LangChain", "framework", ("랭체인",)),
    Skill("pytorch", "PyTorch", "framework", ("파이토치",)),
    Skill("tensorflow", "TensorFlow", "framework", ("텐서플로우", "텐서플로")),
    Skill("keras", "Keras", "framework", ("케라스",)),
    Skill("scikit-learn", "scikit-learn", "framework", ("사이킷런", "sklearn")),
    Skill("huggingface", "Hugging Face", "framework", ("허깅페이스", "Transformers")),
    Skill("nuxtjs", "Nuxt.js", "framework", ("NuxtJS", "넉스트"), implies=("vue",)),
    Skill("jquery", "jQuery", "framework", ("제이쿼리",), implies=("javascript",)),
    Skill("redux", "Redux", "framework", ("리덕스",), implies=("react",)),
    Skill("tailwind", "Tailwind CSS", "framework", ("테일윈드", "TailwindCSS"), implies=("css",)),
    Skill("bootstrap", "Bootstrap", "framework", ("부트스트랩",), implies=("css",)),
    Skill("electron", "Electron", "framework", ("일렉트론",)),
    Skill("dotnet", ".NET", "framework", ("닷넷", "dotnet")),
    Skill("aspnet", "ASP.NET", "framework", (), implies=("dotnet", "csharp")),
    Skill("laravel", "Laravel", "framework", ("라라벨",), implies=("php",)),
    Skill("rails", "Ruby on Rails", "framework", ("레일즈", "레일스"), implies=("ruby",)),
    Skill("celery", "Celery", "framework", ("셀러리",)),
    Skill("unity", "Unity", "framework", ("유니티",), implies=("csharp",)),
    Skill("unreal", "Unreal Engine", "framework", ("언리얼", "언리얼 엔진"), implies=("cpp",)),

    # --- 데이터베이스 ---
    # 관계형 DB 들은 RDBMS·SQL 을 함의한다 — MySQL 을 썼다면 SQL 을 쓴 것이다.
    Skill("mysql", "MySQL", "database", ("마이에스큐엘",), implies=("rdbms", "sql")),
    # MariaDB 는 MySQL 호환이지만 다른 제품이다. 별칭으로 뭉개면 이력서의 "MariaDB" 가
    # 결과에 "MySQL" 로 둔갑한다. 별칭은 '같은 것의 다른 표기'일 때만 쓴다.
    Skill("mariadb", "MariaDB", "database", ("마리아DB", "마리아디비"), implies=("rdbms", "sql")),
    Skill("postgresql", "PostgreSQL", "database", ("Postgres", "포스트그레스", "포스트그레SQL"),
          implies=("rdbms", "sql")),
    Skill("oracle", "Oracle", "database", ("오라클",), implies=("rdbms", "sql")),
    Skill("mongodb", "MongoDB", "database", ("몽고DB", "몽고디비", "Mongo")),
    Skill("redis", "Redis", "database", ("레디스",)),
    # "ES" 는 별칭에서 뺐다 — JavaScript 의 "ES6" 와 충돌해 엉뚱한 스킬로 해석된다.
    Skill("elasticsearch", "Elasticsearch", "database", ("ElasticSearch", "엘라스틱서치")),
    Skill("rdbms", "RDBMS", "database", ("관계형 데이터베이스", "관계형DB", "RDB")),
    Skill("mssql", "SQL Server", "database", ("MSSQL", "MS-SQL", "Microsoft SQL Server"),
          implies=("rdbms", "sql")),
    Skill("sqlite", "SQLite", "database", (), implies=("rdbms", "sql")),
    Skill("dynamodb", "DynamoDB", "database", ("다이나모DB",)),
    Skill("cassandra", "Cassandra", "database", ("카산드라",)),
    Skill("neo4j", "Neo4j", "database", ()),
    Skill("memcached", "Memcached", "database", ("멤캐시드",)),
    Skill("snowflake", "Snowflake", "database", ("스노우플레이크",)),
    Skill("bigquery", "BigQuery", "database", ("빅쿼리",), implies=("gcp",)),
    Skill("redshift", "Redshift", "database", ("레드시프트",), implies=("aws",)),

    # --- 클라우드 ---
    Skill("aws", "AWS", "cloud", ("Amazon Web Services", "아마존 웹서비스")),
    Skill("gcp", "GCP", "cloud", ("Google Cloud", "구글 클라우드")),
    Skill("azure", "Azure", "cloud", ("애저", "Microsoft Azure")),
    Skill("ncp", "NCP", "cloud", ("네이버 클라우드", "Naver Cloud")),
    Skill("ec2", "EC2", "cloud", (), implies=("aws",)),
    Skill("s3", "S3", "cloud", (), implies=("aws",)),
    Skill("lambda", "Lambda", "cloud", ("AWS Lambda", "람다"), implies=("aws",)),
    Skill("firebase", "Firebase", "cloud", ("파이어베이스",)),

    # --- 데브옵스/인프라 ---
    # "컨테이너"는 도구명이 아니라 일반 개념이라 별칭에서 뺐다("컨테이너 오케스트레이션"→Docker 오탐).
    Skill("docker", "Docker", "devops", ("도커",)),
    Skill("kubernetes", "Kubernetes", "devops", ("K8s", "쿠버네티스")),
    Skill("jenkins", "Jenkins", "devops", ("젠킨스",)),
    Skill("github-actions", "GitHub Actions", "devops", ("깃허브 액션",)),
    Skill("terraform", "Terraform", "devops", ("테라폼",)),
    Skill("nginx", "Nginx", "devops", ("엔진엑스",)),
    Skill("linux", "Linux", "devops", ("리눅스", "Unix", "유닉스")),
    Skill("git", "Git", "devops", ("깃", "GitHub", "깃허브", "GitLab")),
    Skill("cicd", "CI/CD", "devops", ("CICD", "지속적 통합", "지속적 배포")),
    Skill("msa", "MSA", "devops", ("마이크로서비스", "Microservices", "마이크로 서비스")),
    Skill("kafka", "Kafka", "devops", ("카프카", "Apache Kafka")),
    Skill("rabbitmq", "RabbitMQ", "devops", ("래빗MQ",)),
    Skill("grafana", "Grafana", "devops", ("그라파나",)),
    Skill("prometheus", "Prometheus", "devops", ("프로메테우스",)),
    Skill("ansible", "Ansible", "devops", ("앤서블",)),
    Skill("helm", "Helm", "devops", ("헬름",), implies=("kubernetes",)),
    Skill("argocd", "ArgoCD", "devops", ("아르고CD", "Argo CD"), implies=("kubernetes",)),
    Skill("tomcat", "Tomcat", "devops", ("톰캣",)),
    Skill("gradle", "Gradle", "devops", ("그레이들",)),
    Skill("maven", "Maven", "devops", ("메이븐",)),
    Skill("webpack", "Webpack", "devops", ("웹팩",)),
    Skill("vite", "Vite", "devops", ("비트",)),

    # --- 데이터 ---
    Skill("spark", "Spark", "data", ("Apache Spark", "스파크")),
    Skill("airflow", "Airflow", "data", ("Apache Airflow", "에어플로우")),
    Skill("hadoop", "Hadoop", "data", ("하둡",)),
    Skill("pandas", "pandas", "data", ("판다스",)),
    Skill("numpy", "NumPy", "data", ("넘파이",)),
    Skill("opencv", "OpenCV", "data", ()),
    Skill("flink", "Flink", "data", ("Apache Flink", "플링크")),
    Skill("hive", "Hive", "data", ("Apache Hive", "하이브")),
    Skill("tableau", "Tableau", "data", ("태블로",)),
    Skill("mlflow", "MLflow", "data", ()),
    Skill("kubeflow", "Kubeflow", "data", ("쿠브플로우",), implies=("kubernetes",)),

    # --- 테스트 ---
    Skill("junit", "JUnit", "testing", ("제이유닛",)),
    Skill("jest", "Jest", "testing", ()),
    Skill("pytest", "pytest", "testing", ()),
    Skill("tdd", "TDD", "testing", ("테스트 주도 개발",)),
    Skill("selenium", "Selenium", "testing", ("셀레니움",)),
    Skill("cypress", "Cypress", "testing", ("사이프레스",)),
    Skill("playwright", "Playwright", "testing", ("플레이라이트",)),
    Skill("jmeter", "JMeter", "testing", ("제이미터",)),
    Skill("mockito", "Mockito", "testing", ("모키토",)),
    Skill("postman", "Postman", "testing", ("포스트맨",)),

    # --- 기타 개념 ---
    Skill("rest-api", "REST API", "etc", ("RESTful", "RESTful API", "REST", "레스트 API")),
    Skill("graphql", "GraphQL", "etc", ("그래프QL",)),
    Skill("grpc", "gRPC", "etc", ()),
    Skill("oauth", "OAuth", "etc", ("OAuth2", "OAuth 2.0", "소셜 로그인")),
    Skill("websocket", "WebSocket", "etc", ("웹소켓",)),
    Skill("jwt", "JWT", "etc", ("JSON Web Token",)),
    # 채용공고 관행상 Swagger 와 OpenAPI 는 같은 것을 가리키는 경우가 대부분이라 별칭으로 묶는다.
    Skill("openapi", "OpenAPI", "etc", ("Swagger", "스웨거")),
    Skill("webrtc", "WebRTC", "etc", ()),
    # 모바일 플랫폼 — 언어·프레임워크가 아니라 etc 로 분류
    Skill("android", "Android", "etc", ("안드로이드", "AOS")),
    Skill("ios", "iOS", "etc", ("아이오에스",)),
)


# --- 대체군 (D99) ------------------------------------------------------------------
#
# 공고가 "A / B / C 중 하나"로 요구하는 묶음. 파서는 그 OR 관계를 잃고 techStack 을 평면
# 목록으로 만들기 때문에, 요구 기술이 부풀고 **그 부풀린 수가 판정 점수의 분모가 된다** —
# 실측(2026-08-01, 콘센트릭스 Agent 엔지니어 공고): techStack 22개 중 택일 관계가 다수여서
# 실제 요구 역량 ~8개가 22개로 세어졌고, pgvector 만 아는 지원자가 벡터DB 자리에서 1/5 로
# 깎였다(`_match_by_skills` 는 matched_ratio ≥ 0.8 을 met 으로 본다). 등급 왜곡이고, 낮은
# 등급은 `observe_rules ① 약한 판정` 을 발동시켜 사용자가 청한 자소서·면접을 큐에서 뺀다.
#
# **명백한 것만 넣는다.** 애매한 묶음(Kafka~RabbitMQ, Kubernetes~ECS)은 넣지 않았다 — 공고가
# 특정 하나를 원하는 경우가 많고, 갈리는 판단을 사전에 못 박는 것은 §3-1 이 경고하는 실수다.
# 여기 있는 다섯은 공고 문면에서 "중 하나"로 나오는 것이 관례인 군이다.
_ALTERNATE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("벡터 DB", ("Pinecone", "Qdrant", "Milvus", "Weaviate", "pgvector", "Chroma", "FAISS")),
    ("클라우드", ("AWS", "GCP", "Azure")),
    ("워크플로 오케스트레이터", ("Airflow", "Dagster", "Prefect", "Luigi")),
    ("LLM 프레임워크", ("LangChain", "LlamaIndex", "Haystack", "LangGraph")),
    ("LLM API", ("OpenAI", "Anthropic", "Gemini")),
)

# 표준 표시명(소문자) → 대체군 이름. `alternate_group` 이 읽는 역인덱스.
_ALTERNATE_OF: dict[str, str] = {
    member.lower(): group for group, members in _ALTERNATE_GROUPS for member in members
}


def _alias_index() -> dict[str, Skill]:
    """소문자 별칭 → Skill. canonical/key 도 자동으로 별칭에 포함한다."""

    index: dict[str, Skill] = {}
    for skill in _SKILLS:
        for alias in (skill.canonical, skill.key, *skill.aliases):
            index.setdefault(_normalize_key(alias), skill)
    return index


def _flexible(alias: str) -> str:
    """별칭을 '구분자에 관대한' 정규식 조각으로. "Node.js" → `Node[.\\s\\-_]*js`.

    별칭 안의 구분자(., 공백, -, _)를 0개 이상 허용으로 바꾼다. 그래서 원문에
    "Node js" / "NodeJS" / "Node-js" 어떻게 적혀 있어도 하나의 등록 별칭으로 다 잡힌다
    (붙여 쓴 형태까지 포함). 이게 dict 조회(`_normalize_key`)의 구분자 무시와 짝을 이룬다.
    """

    parts = [re.escape(p) for p in _SEPARATORS.split(alias) if p]
    return r"[.\s\-_]*".join(parts)


def _search_pattern() -> re.Pattern[str]:
    """원문에서 별칭을 찾는 정규식.

    - 긴 별칭 우선(길이 내림차순): "Node.js" 가 "Node" 보다 먼저 매칭돼야 한다.
      (정규식 alternation 은 먼저 쓴 대안을 우선 시도한다)
    - 구분자 유연 매칭: 각 별칭은 `_flexible` 로 확장돼 띄어쓰기/점/하이픈 변형을 흡수한다.
    - 경계: 앞뒤가 영숫자/`+`/`#` 면 매칭하지 않는다. "Java" 가 "JavaScript" 안에서
      잡히는 것을 막는다. 한글은 경계로 취급해 "자바스크립트"·"스프링부트" 가 정상 매칭된다.
    """

    seen: set[str] = set()
    aliases: list[str] = []
    for skill in _SKILLS:
        for alias in (skill.canonical, skill.key, *skill.aliases):
            if alias not in seen and _is_searchable(alias):
                seen.add(alias)
                aliases.append(alias)
    aliases.sort(key=len, reverse=True)
    body = "|".join(_flexible(a) for a in aliases)
    return re.compile(rf"(?<![A-Za-z0-9+#])(?:{body})(?![A-Za-z0-9+#])", re.IGNORECASE)


class SkillTaxonomy:
    """스킬명 표준화기. 동의어 흡수 → 표준 표시명/카테고리.

    **하이브리드**(2026-07-20 결정): 사전(룰)이 먼저다 — 무료·즉시·결정론이라 알려진
    표기는 전부 여기서 끝난다. 사전에 없는 표기만 임베딩 유사도로 보조 판단한다
    (`_resolve_by_embedding`). 임베딩이 미연결이면(`NullEmbedder`) 이 보조 경로는
    조용히 건너뛰고 지금과 동일하게 동작한다 — 폴백이 전체 실패로 번지지 않는다.
    """

    def __init__(self) -> None:
        self._index = _alias_index()
        self._pattern = _search_pattern()
        # 임베딩 비교 대상 = 표준 표시명 목록(중복 제거). resolve() 폴백에서만 쓴다.
        self._canonical_skills: list[Skill] = list({s.key: s for s in _SKILLS}.values())
        # 임베딩 폴백 결과 메모 (2026-07-23 성능 개선) — similarity_matrix 가 호출마다
        # 표준명 전체를 다시 임베딩하므로, 같은 미등록 표기가 반복될 때마다 API 를 다시
        # 부르면 프로필 빌드가 분 단위로 느려진다. 결과(None 포함)를 표기별로 기억한다.
        self._embed_memo: dict[str, Skill | None] = {}
        # embedder 는 저장해두지 않고 매번 get_embedder() 로 새로 받는다(_resolve_by_embedding).
        # 이 인스턴스 자체가 lru_cache 로 프로세스당 하나만 만들어지므로, __init__ 에서 한 번
        # 잡아두면 테스트/런타임에서 provider 를 바꿔도 낡은 embedder 를 계속 쓰게 된다
        # (gap_matcher.get_gap_matcher() 와 동일한 이유, §` gap_matcher.py` 주석 참고).

    def resolve(self, raw: str) -> Skill | None:
        """원문 표기 → Skill. 사전에 없으면 임베딩 유사도로 한 번 더 시도한다."""

        skill = self._index.get(_normalize_key(raw))
        if skill:
            return skill
        return self._resolve_by_embedding(raw)

    def _resolve_by_embedding(self, raw: str) -> Skill | None:
        """사전에 없는 표기를 표준 스킬명들과 의미 비교해 가장 가까운 걸 찾는다.

        "관련 있음"이 아니라 "같은 것"이라고 단정하는 자리라 임계값을 높게 잡는다
        (_EMBED_SKILL_MATCH). 임베딩이 없거나(NullEmbedder) 결과가 애매하면 None —
        모르는 걸 억지로 매칭시키지 않는다(§ '모른다'와 '아니다'의 구분과 동일 원칙).
        """

        text = (raw or "").strip()
        if not text:
            return None

        memo_key = _normalize_key(text)
        if memo_key in self._embed_memo:
            return self._embed_memo[memo_key]

        names = [s.canonical for s in self._canonical_skills]
        matrix = get_embedder().similarity_matrix([text], names)
        if not matrix or not matrix[0]:
            # 임베딩 미연결(NullEmbedder)은 '판정 안 함'이라 메모하지 않는다 —
            # 나중에 provider 가 연결되면 다시 시도할 수 있어야 한다.
            return None

        scores = matrix[0]
        best_idx = max(range(len(scores)), key=lambda i: scores[i])
        result = (
            self._canonical_skills[best_idx] if scores[best_idx] >= _EMBED_SKILL_MATCH else None
        )
        self._embed_memo[memo_key] = result
        return result

    def normalize(self, raw: str) -> str:
        """원문 표기 → 표준 표시명. 사전에 없으면 원문을 다듬어 그대로 돌려준다.

        모르는 기술이라고 버리면 안 된다 — 신기술은 항상 사전보다 먼저 나온다.
        표준화만 못 할 뿐 요구사항으로는 살아 있어야 한다.
        """

        skill = self.resolve(raw)
        return skill.canonical if skill else (raw or "").strip()

    def normalize_all(self, raws: list[str]) -> list[str]:
        """목록 표준화 + 중복 제거(입력 순서 유지). 동의어는 하나로 합쳐진다."""

        seen: set[str] = set()
        out: list[str] = []
        for raw in raws:
            name = self.normalize(raw)
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
        return out

    def find_in_text(self, text: str) -> list[str]:
        """원문에서 알려진 스킬을 전부 찾아 표준 표시명으로 (등장 순서, 중복 제거).

        `rule_extractor` 의 1차 추출이 이걸 쓴다 — LLM 없이 명시된 기술을 확정한다.
        """

        seen: set[str] = set()
        out: list[str] = []
        for match in self._pattern.finditer(text or ""):
            skill = self._index.get(_normalize_key(match.group(0)))
            if skill and skill.key not in seen:
                seen.add(skill.key)
                out.append(skill.canonical)
        return out

    def alternate_group(self, raw: str) -> str | None:
        """이 스킬이 속한 **대체군** 이름. 없으면 None. (D99 — OR 요구를 하나로 세기 위해)

        `normalize` 와 다른 연산이다. 표준화는 같은 기술의 다른 표기를 **한 키로 합치는**
        것이고(ReactJS = React), 대체군은 **다른 기술을 한 요구사항으로 세는** 것이다
        (pgvector ≠ Pinecone, 그러나 공고는 둘 중 하나를 원한다). 그래서 여기서 키를
        합치지 않는다 — 이 모듈 상단의 "React~Vue 를 합치면 안 된다"는 선은 그대로다.
        """

        name = self.normalize(raw).lower()
        return _ALTERNATE_OF.get(name)

    def category_of(self, raw: str) -> SkillCategory:
        """스킬의 카테고리. 모르는 기술은 'etc'. (gap_matcher 의 scoreBasis 집계용)"""

        skill = self.resolve(raw)
        return skill.category if skill else "etc"

    def is_known(self, raw: str) -> bool:
        """사전에 등재된 기술인지. (모르는 기술 비율을 warning 으로 알릴 때 사용)"""

        return self.resolve(raw) is not None

    def implied_by(self, raw: str) -> list[str]:
        """이 스킬이 수반하는 스킬들의 표준 표시명 (재귀 — Next.js → React)."""

        skill = self.resolve(raw)
        if not skill:
            return []
        out: list[str] = []
        stack = list(skill.implies)
        seen: set[str] = {skill.key}
        while stack:
            key = stack.pop()
            if key in seen:
                continue
            seen.add(key)
            implied = self._index.get(key)
            if implied:
                out.append(implied.canonical)
                stack.extend(implied.implies)
        return out

    def with_implied(self, raws: list[str]) -> list[str]:
        """스킬 목록 + 그것들이 수반하는 스킬들 (표준명, 중복 제거).

        "MySQL 경험" → ["MySQL", "RDBMS", "SQL"]. 요구사항이 상위 개념("RDBMS 설계")으로
        적혀 있어도 구체 제품 경험으로 충족되게 만드는 핵심 확장이다.
        """

        expanded: list[str] = []
        for raw in raws:
            expanded.append(raw)
            expanded.extend(self.implied_by(raw))
        return self.normalize_all(expanded)

    def aliases_of(self, raw: str) -> list[str]:
        """해당 스킬의 모든 표기(표준명 포함). gap_matcher 의 1차 동의어 매칭이 쓴다."""

        skill = self.resolve(raw)
        if not skill:
            return [(raw or "").strip()]
        return [skill.canonical, *skill.aliases]


@lru_cache(maxsize=1)
def get_skill_taxonomy() -> SkillTaxonomy:
    """프로세스당 하나를 재사용한다(별칭 인덱스·정규식 컴파일 비용 회피).

    운영 전환 시 여기서 외부 DB 로드 구현체를 반환하도록 바꾸면 노드 코드는 불변.
    """

    return SkillTaxonomy()
