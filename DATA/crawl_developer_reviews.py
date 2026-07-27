"""공개 블로그의 개발자 합격 후기를 수집해 SQLite와 JSON으로 저장한다."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
import urllib.robotparser
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


BASE = "https://search.naver.com/search.naver?where=web&query="
USER_AGENT = "JobisReviewCrawler/1.0 (public pages; educational research)"
DB = Path("data/developer_reviews/reviews.db")
OUT = Path("exports/review_articles.json")
FIELDS = (
    "source",
    "review_id",
    "company",
    "title",
    "url",
    "outcome",
    "role",
    "stages",
    "detail_text",
    "text_length",
    "collected_at",
)
QUERIES = (
    'site:tistory.com "네이버" "개발자" "최종 합격"',
    'site:tistory.com "카카오" "개발자" "최종 합격"',
    'site:tistory.com "라인" "개발자" "최종 합격"',
    'site:tistory.com "쿠팡" "개발자" "최종 합격"',
    'site:tistory.com "토스" "개발자" "최종 합격"',
    'site:tistory.com "삼성" "소프트웨어" "최종 합격"',
    'site:tistory.com "현대" "IT" "최종 합격"',
    'site:velog.io "백엔드" "최종 합격" 후기',
    'site:velog.io "프론트엔드" "최종 합격" 후기',
    'site:tistory.com "백엔드" "합격 후기"',
    'site:tistory.com "프론트엔드" "합격 후기"',
    'site:tistory.com "소프트웨어 엔지니어" "합격 후기"',
    'site:velog.io "개발자" "최종 합격" 후기',
    'site:tistory.com "개발자" "최종 합격" 후기',
)
CONTENT_HOSTS = ("tistory.com", "velog.io", "blog.naver.com", "medium.com", "github.io")
COMPANIES = ("네이버", "카카오", "라인", "쿠팡", "토스", "삼성", "현대", "LG", "당근")
TRAINING_SIGNALS = (
    "ssafy", "싸피", "우아한테크코스", "우테코", "부트캠프", "데브코스",
    "소프트웨어 마에스트로", "sw 마에스트로", "에이블스쿨", "aivle", "교육과정",
)
ROLE_RULES = (
    ("백엔드", ("백엔드", "backend", "서버 개발")),
    ("프론트엔드", ("프론트엔드", "frontend", "front-end")),
    ("데이터·ML", ("데이터 엔지니어", "데이터 분석", "머신러닝", "ai 개발")),
    ("DevOps·인프라", ("devops", "데브옵스", "클라우드 엔지니어", "인프라 엔지니어")),
    ("Android", ("android", "안드로이드")),
    ("iOS", ("ios", "swift")),
    ("풀스택", ("풀스택", "fullstack", "full-stack")),
)
STAGE_RULES = (
    ("서류", ("서류", "이력서", "자기소개서", "포트폴리오")),
    ("코딩테스트", ("코딩테스트", "코딩 테스트", "코테")),
    ("과제", ("사전과제", "사전 과제", "과제 전형")),
    ("기술면접", ("기술면접", "기술 면접", "실무 면접")),
    ("인성·문화면접", ("인성면접", "인성 면접", "컬처핏", "문화면접")),
    ("최종면접", ("최종면접", "최종 면접", "임원면접", "임원 면접")),
)
ROBOTS: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.2)
    parser.add_argument("--query", action="append", default=[], help="지정한 검색어만 사용(반복 가능)")
    parser.add_argument("--prune", action="store_true", help="기존 DB에서 교육·자격증·탈락 후기를 제거")
    return parser.parse_args()


def make_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1200")
    options.add_argument("--lang=ko-KR")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-agent={USER_AGENT}")
    return webdriver.Chrome(options=options)


def allowed_by_robots(url: str) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    parser = ROBOTS.get(origin)
    if parser is None and origin not in ROBOTS:
        try:
            request = urllib.request.Request(f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=5) as response:
                lines = response.read(512_000).decode("utf-8", "replace").splitlines()
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(lines)
        except Exception:
            parser = None
        ROBOTS[origin] = parser
    return bool(parser and parser.can_fetch(USER_AGENT, url))


def search(driver: webdriver.Chrome, query: str) -> list[str]:
    driver.get(BASE + quote_plus(query))
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    urls: list[str] = []
    for anchor in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
        url = anchor.get_attribute("href")
        if not url or not url.startswith(("http://", "https://")):
            continue
        host = urlparse(url).netloc.lower().split(":", 1)[0]
        if not any(host == suffix or host.endswith("." + suffix) for suffix in CONTENT_HOSTS):
            continue
        if host == "blog.naver.com":
            url = url.replace("https://blog.naver.com/", "https://m.blog.naver.com/", 1)
        url = url.split("#", 1)[0]
        if url not in urls:
            urls.append(url)
    return urls


EXTRACT_SCRIPT = """
const root = document.querySelector('[itemprop="articleBody"], .entry-content, .article_view, .post-content, .tt_article_useless_p_margin, .se-main-container, article, main, [role="main"], #content') || document.body;
const copy = root.cloneNode(true);
copy.querySelectorAll('script,style,noscript,nav,header,footer,aside,form,button,iframe,svg,.advertisement,[class*="advert"],[id*="advert"],#comments,.comments,[class*="comment"],[id*="comment"],.related-posts,[class*="related"],.share,[class*="share"],.tags').forEach(el => el.remove());
return {title: (document.querySelector('h1')?.innerText || document.title || '').trim(), text: (copy.innerText || copy.textContent || '').replace(/\\u00a0/g, ' ').replace(/\\n{3,}/g, '\\n\\n').trim()};
"""


def classify(title: str, text: str) -> tuple[str | None, str, str]:
    lowered = text.lower()
    # 본문에는 비교 대상 기업이 함께 언급될 수 있으므로 제목에서만 기업명을 판정한다.
    company = next((name for name in COMPANIES if name.lower() in title.lower()), None)
    role = next((name for name, words in ROLE_RULES if any(word in lowered for word in words)), "개발 일반·불명")
    stages = ",".join(name for name, words in STAGE_RULES if any(word in lowered for word in words))
    return company, role, stages


def crawl(driver: webdriver.Chrome, url: str) -> dict | None:
    if not allowed_by_robots(url):
        print(f"[reviews] status=skipped reason=robots url={url}", flush=True)
        return None
    try:
        driver.get(url)
        WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(0.8)
        extracted = driver.execute_script(EXTRACT_SCRIPT)
    except (TimeoutException, WebDriverException) as exc:
        print(f"[reviews] status=error error={type(exc).__name__} url={url}", flush=True)
        return None
    text = re.sub(r"\n[ \t]+", "\n", extracted.get("text", "")).strip()
    lowered = f"{extracted.get('title', '')}\n{text}".lower()
    if len(text) < 300:
        print(f"[reviews] status=skipped reason=detail_too_short url={url}", flush=True)
        return None
    title = extracted.get("title", "").strip()
    if any(word in title for word in ("불합격", "탈락", "광탈")):
        print(f"[reviews] status=skipped reason=non_acceptance_title url={url}", flush=True)
        return None
    if not ("합격" in lowered and ("후기" in lowered or "회고" in lowered)):
        print(f"[reviews] status=skipped reason=not_acceptance_review url={url}", flush=True)
        return None
    if not any(word in lowered for word in ("개발", "엔지니어", "프로그래머", "코딩", "소프트웨어")):
        print(f"[reviews] status=skipped reason=not_developer_review url={url}", flush=True)
        return None
    if any(word in lowered[:1200] for word in ("정보처리기사", "sqld", "sqlp", "자격증 시험")):
        print(f"[reviews] status=skipped reason=certification_review url={url}", flush=True)
        return None
    if any(word in lowered[:1400] for word in TRAINING_SIGNALS):
        print(f"[reviews] status=skipped reason=training_review url={url}", flush=True)
        return None
    company, role, stages = classify(title, lowered)
    return {
        "source": "취업 후기",
        "review_id": hashlib.sha256(driver.current_url.encode()).hexdigest()[:16],
        "company": company,
        "title": title,
        "url": driver.current_url.split("#", 1)[0],
        "outcome": "합격",
        "role": role,
        "stages": stages,
        "detail_text": text,
        "text_length": len(text),
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def save(records: list[dict]) -> int:
    DB.parent.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS review_articles (" + ", ".join(f"{field} TEXT" for field in FIELDS) + ", UNIQUE(url))"
        )
        for record in records:
            connection.execute(
                "INSERT INTO review_articles VALUES (" + ", ".join("?" for _ in FIELDS) + ") "
                "ON CONFLICT(url) DO UPDATE SET "
                + ", ".join(f"{field}=excluded.{field}" for field in FIELDS if field != "url"),
                [record[field] for field in FIELDS],
            )
        rows = [dict(zip(FIELDS, row)) for row in connection.execute("SELECT " + ", ".join(FIELDS) + " FROM review_articles ORDER BY collected_at DESC, review_id")]
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(rows)


def existing_urls() -> set[str]:
    if not DB.exists():
        return set()
    with sqlite3.connect(DB) as connection:
        try:
            return {row[0] for row in connection.execute("SELECT url FROM review_articles")}
        except sqlite3.OperationalError:
            return set()


def is_excluded(title: str, text: str) -> bool:
    lowered = text.lower()
    return (
        any(word in title for word in ("불합격", "탈락", "광탈"))
        or any(word in lowered[:1200] for word in ("정보처리기사", "sqld", "sqlp", "자격증 시험"))
        or any(word in lowered[:1400] for word in TRAINING_SIGNALS)
    )


def prune_existing() -> tuple[int, int]:
    if not DB.exists():
        return 0, 0
    with sqlite3.connect(DB) as connection:
        rows = connection.execute("SELECT url, title, detail_text FROM review_articles").fetchall()
        urls = [url for url, title, text in rows if is_excluded(title, text)]
        connection.executemany("DELETE FROM review_articles WHERE url = ?", [(url,) for url in urls])
    return len(urls), save([])


def main() -> int:
    args = parse_args()
    if args.max_results < 1 or args.delay < 0.5:
        raise SystemExit("--max-results는 1 이상, --delay는 0.5 이상이어야 합니다.")
    if args.prune:
        removed, total = prune_existing()
        print(f"[reviews] status=pruned removed={removed} records={total}", flush=True)
        return 0
    driver = make_driver()
    records: list[dict] = []
    seen = existing_urls()
    try:
        for query in args.query or QUERIES:
            candidates = search(driver, query)
            for url in candidates:
                if len(records) >= args.max_results:
                    break
                if url in seen:
                    print(f"[reviews] status=skipped reason=duplicate url={url}", flush=True)
                    continue
                record = crawl(driver, url)
                if record:
                    records.append(record)
                    seen.add(record["url"])
                    # 중단돼도 수집된 후기를 잃지 않도록 즉시 저장한다.
                    save([record])
                    print(f"[reviews] status=saved count={len(records)}/{args.max_results} title={record['title']!r} url={record['url']}", flush=True)
                time.sleep(args.delay)
            if len(records) >= args.max_results:
                break
    finally:
        driver.quit()
    total = save([])
    print(f"[reviews] status=completed new_records={len(records)} records={total} db={DB} json={OUT}", flush=True)
    return 0 if records else 2


if __name__ == "__main__":
    raise SystemExit(main())
