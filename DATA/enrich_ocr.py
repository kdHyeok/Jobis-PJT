"""이미지형(need_ocr="O") 공고의 이미지에서 로컬 OCR로 본문 텍스트를 채운다.

- LLM API를 쓰지 않는다. EasyOCR(로컬, 무료) + OpenCV 전처리 + 규칙 기반 후처리.
- 크롤러와 같은 철학: 한 건씩 처리하고 --checkpoint-every 마다 중간 저장, 재개 지원.
- 긴 상세 이미지는 세로로 잘라(slice) 조각별로 읽고, 여러 장이면 순서대로 이어붙인다.
- OCR 결과가 크롤러와 같은 품질 기준(담당업무+자격요건, 최소 길이)을 통과할 때만 채택한다.

실행(가상환경 파이썬으로):
    # 0) 설치 확인 - 이미지 URL 하나만 OCR 해서 결과 출력
    .venv/bin/python enrich_ocr.py --test-url "<이미지 URL>"

    # 1) 특정 사이트의 이미지형 공고를 OCR (기본: 원본 안 건드리고 *_ocr.json 로 저장)
    .venv/bin/python enrich_ocr.py --site jobkorea --max 50

    # 2) 결과를 원본 JSON/DB 에 반영 (해당 사이트 크롤러가 '끝난 뒤'에만!)
    .venv/bin/python enrich_ocr.py --site jobkorea --in-place

주의: --in-place 는 크롤러가 쓰는 원본 JSON을 덮어쓴다. 그 사이트 크롤러가
실행 중이면 먼저 끝낸 뒤에 --in-place 로 돌릴 것(같은 파일을 동시에 쓰면 충돌).
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

from crawl_jobkorea_it import (
    FIELDS,
    has_complete_text_detail,
    load_existing_rows,
)

# 사이트별 입력(크롤러가 만든 JSON)과 DB 경로
SITES = {
    "jobkorea": (
        Path("exports/jobkorea_job_postings.json"),
        Path("data/jobkorea_job_postings/jobkorea_job_postings.db"),
    ),
    "saramin": (
        Path("exports/saramin_job_postings.json"),
        Path("data/saramin_job_postings/saramin_job_postings.db"),
    ),
    "wanted": (
        Path("exports/wanted_job_postings.json"),
        Path("data/wanted_job_postings/wanted_job_postings.db"),
    ),
    "incruit": (
        Path("exports/incruit_job_postings.json"),
        Path("data/incruit_job_postings/incruit_job_postings.db"),
    ),
    "work24": (
        Path("exports/work24_job_postings.json"),
        Path("data/work24_job_postings/work24_job_postings.db"),
    ),
}

USER_AGENT = "Mozilla/5.0 (compatible; JobisResearchBot/1.0; +local-study)"

# 채용공고 상세 이미지에 자주 섞이는 장식/안내 문구. OCR 결과에서 걸러낸다.
NOISE_LINE_PATTERNS = (
    r"^\s*$",
    r"지원하기$",
    r"^\W{0,3}$",  # 아이콘만 인식된 짧은 기호
)

# 이 공고가 '실제 채용공고 본문'임을 알려주는 신호 단어. 라벨이 캐주얼하거나 OCR
# 오탈자가 있어도 걸리도록 짧고 견고한 조각으로 둔다. 정식 라벨(담당업무·자격요건)만
# 고집하면 토스처럼 '함께할 업무예요/지원하실 수 있어요' 식 공고를 놓친다.
JOB_SIGNAL_WORDS = (
    "업무", "담당", "자격", "지원", "경력", "우대", "경험", "채용", "모집",
    "역량", "합류", "구성원", "기술", "스택", "직무", "우리", "팀",
)

# 한글 OCR이 거의 항상 틀리는 안전한 교정만 모았다(정상 단어를 깨뜨리지 않는 것).
OCR_FIXES = (
    ("잇어", "있어"), ("잇는", "있는"), ("잇게", "있게"), ("잇고", "있고"),
    ("잇도록", "있도록"), ("잇으", "있으"), ("잇다", "있다"), ("잇지", "있지"),
    ("안는", "않는"), ("안고", "않고"), ("안아", "않아"),
)


def fix_common_ocr(text: str) -> str:
    """가장 흔한 OCR 오탈자만 보수적으로 교정한다(가독성 보정)."""
    for wrong, right in OCR_FIXES:
        text = text.replace(wrong, right)
    return text


def ocr_text_is_usable(text: str, min_chars: int, min_signals: int = 3) -> bool:
    """OCR 결과를 채택할지 판정한다.

    정식 라벨을 요구하는 크롤러 기준(has_complete_text_detail)과 달리, 이미지형 공고를
    최대한 살리기 위해 '충분한 길이 + 채용공고 신호 단어 여러 개'로 완화한다. 로고·표지처럼
    글자가 거의 없는 이미지는 길이/신호에서 걸러진다.
    """
    compact = re.sub(r"\s+", "", text)
    if len(compact) < min_chars:
        return False
    hits = sum(1 for word in JOB_SIGNAL_WORDS if word in compact)
    return hits >= min_signals

_engine = None  # (종류, 엔진) — OCR 모델은 무거우므로 한 번만 만든다.


def get_engine(use_gpu: bool, prefer: str = "auto"):
    """OCR 엔진을 지연 생성한다.

    측정 결과(토스 공고 CER 비교) PaddleOCR의 한국어 오독이 압도적으로 적어(치환 4자
    vs EasyOCR 294자) PaddleOCR을 기본으로 쓰고, 사용 불가 환경에서는 EasyOCR로
    대체한다. --engine 으로 강제 선택할 수 있다.
    """
    global _engine
    if _engine is not None:
        return _engine
    if prefer in ("auto", "paddle"):
        try:
            import numpy as np
            from paddleocr import PaddleOCR

            print("[ocr] PaddleOCR 모델 로딩 중... (처음엔 모델 다운로드로 시간이 걸립니다)", flush=True)
            # 모델명을 지정하면 lang이 무시되므로 검출·인식 모델을 모두 한국어용으로 명시.
            # enable_mkldnn=False: paddlepaddle 3.x CPU(oneDNN) 버그 회피.
            ocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
                enable_mkldnn=False,
            )
            # CPU 환경에 따라 추론 단계에서 죽는 버그가 있어 예열로 미리 확인한다.
            ocr.predict(np.full((64, 256, 3), 255, dtype=np.uint8))
            _engine = ("paddle", ocr)
            print("[ocr] engine=paddleocr", flush=True)
            return _engine
        except Exception as exc:
            if prefer == "paddle":
                raise SystemExit(f"PaddleOCR 사용 불가: {type(exc).__name__}: {exc}")
            print(f"[ocr] PaddleOCR 사용 불가({type(exc).__name__}) → EasyOCR로 대체", flush=True)
    try:
        import easyocr
    except ImportError as exc:
        raise SystemExit(
            "사용 가능한 OCR 엔진이 없습니다. 가상환경에 설치하세요:\n"
            "    .venv/bin/pip install paddlepaddle paddleocr\n"
            "    (또는) .venv/bin/pip install easyocr\n"
            f"(원인: {exc})"
        )
    print("[ocr] EasyOCR 모델 로딩 중... (처음엔 모델 다운로드로 시간이 걸립니다)", flush=True)
    _engine = ("easy", easyocr.Reader(["ko", "en"], gpu=use_gpu))
    print("[ocr] engine=easyocr", flush=True)
    return _engine


def read_chunk(chunk, use_gpu: bool, prefer: str) -> list[str]:
    """이미지 조각 하나를 현재 엔진으로 읽어 줄 단위 텍스트를 돌려준다."""
    kind, engine = get_engine(use_gpu, prefer)
    if kind == "paddle":
        texts: list[str] = []
        for res in engine.predict(chunk):
            texts.extend(str(t) for t in res["rec_texts"])
        return texts
    # EasyOCR. paragraph=True: 가까운 글자를 문단으로 묶어 읽기 순서를 살린다.
    return [str(t) for t in engine.readtext(chunk, detail=0, paragraph=True)]


def fetch_bytes(url: str, referer: str = "https://www.jobkorea.co.kr/", timeout: int = 40) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Referer": referer})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def decode_image(data: bytes):
    """바이트 이미지를 OpenCV(BGR) 배열로 디코드한다."""
    import cv2
    import numpy as np

    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    return image


def slice_vertical(image, slice_height: int, overlap: int):
    """세로로 긴 이미지를 겹침(overlap)을 두고 위→아래로 자른다."""
    height = image.shape[0]
    if height <= slice_height:
        return [image]
    chunks = []
    top = 0
    step = max(1, slice_height - overlap)
    while top < height:
        bottom = min(top + slice_height, height)
        chunks.append(image[top:bottom])
        if bottom >= height:
            break
        top += step
    return chunks


def upscale_if_small(image, min_width: int = 1000):
    """폭이 좁은 이미지는 2배 확대해 작은 글자 인식률을 높인다."""
    import cv2

    width = image.shape[1]
    if width and width < min_width:
        return cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return image


def dedup_fuzzy(lines: list[str], window: int = 10, threshold: float = 0.9) -> list[str]:
    """슬라이스 겹침으로 생기는 중복 줄을 제거한다.

    겹침 구간을 두 슬라이스가 조금씩 다르게 읽는 경우가 많아 완전 일치만으로는
    못 걸러낸다(CER 측정에서 삽입 오류의 주범). 최근 window줄 안에 '거의 같은'
    줄이 있으면 중복으로 보고 버린다.
    """
    import difflib

    result: list[str] = []
    for line in lines:
        duplicate = False
        for prev in result[-window:]:
            if line == prev or difflib.SequenceMatcher(None, line, prev).ratio() >= threshold:
                duplicate = True
                break
        if not duplicate:
            result.append(line)
    return result


def is_noise(line: str) -> bool:
    return any(re.search(pattern, line) for pattern in NOISE_LINE_PATTERNS)


def ocr_image_bytes(data: bytes, use_gpu: bool, slice_height: int, overlap: int,
                    prefer: str = "auto") -> str:
    """이미지 한 장(바이트)을 전처리·슬라이싱해 OCR 텍스트로 만든다."""
    image = decode_image(data)
    if image is None:
        return ""
    image = upscale_if_small(image)
    lines: list[str] = []
    for chunk in slice_vertical(image, slice_height, overlap):
        for text in read_chunk(chunk, use_gpu, prefer):
            for raw in text.splitlines():
                cleaned = raw.strip()
                if cleaned and not is_noise(cleaned):
                    lines.append(cleaned)
    return "\n".join(dedup_fuzzy(lines))


def ocr_posting(image_urls: list[str], use_gpu: bool, slice_height: int, overlap: int,
                delay: float, prefer: str = "auto") -> str:
    """공고의 이미지들을 순서대로 OCR 해 하나의 본문으로 합친다."""
    parts: list[str] = []
    for index, url in enumerate(image_urls):
        try:
            data = fetch_bytes(url)
            text = ocr_image_bytes(data, use_gpu, slice_height, overlap, prefer)
            if text:
                parts.append(text)
        except Exception as exc:
            print(f"  [ocr] image={index} status=error error={type(exc).__name__}", flush=True)
        time.sleep(delay)
    return "\n".join(parts).strip()


def save(rows: list[dict], json_path: Path, db_path: Path) -> None:
    """크롤러와 동일한 스키마(FIELDS)로 JSON과 DB를 함께 갱신한다."""
    import sqlite3

    json_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # 스키마에 없는 보조 키는 저장에서 제외한다.
    ordered = [{field: row.get(field) for field in FIELDS} for row in rows]
    json_path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE IF EXISTS job_postings")
        connection.execute(
            "CREATE TABLE job_postings (" + ", ".join(f"{field} TEXT" for field in FIELDS) + ")"
        )
        connection.executemany(
            "INSERT INTO job_postings VALUES (" + ", ".join("?" for _ in FIELDS) + ")",
            [
                [
                    json.dumps(row.get(field), ensure_ascii=False)
                    if field == "image_urls"
                    else row.get(field)
                    for field in FIELDS
                ]
                for row in ordered
            ],
        )


def load_failed(sidecar: Path) -> set[str]:
    if not sidecar.exists():
        return set()
    return set(json.loads(sidecar.read_text(encoding="utf-8")))


def save_failed(sidecar: Path, failed: set[str]) -> None:
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(sorted(failed), ensure_ascii=False), encoding="utf-8")


def run_test_url(args) -> int:
    """이미지 URL 하나만 OCR 해서 결과를 출력한다(설치·성능 확인용)."""
    print(f"[test] url={args.test_url}", flush=True)
    data = fetch_bytes(args.test_url)
    text = fix_common_ocr(ocr_image_bytes(data, args.gpu, args.slice_height, args.overlap, args.engine))
    print("\n===== OCR 결과 =====\n")
    print(text or "(추출된 텍스트 없음)")
    print("\n===== 판정 =====")
    compact = re.sub(r"\s+", "", text)
    hits = [w for w in JOB_SIGNAL_WORDS if w in compact]
    print(f"글자 수(공백제외): {len(compact)}")
    print(f"채용공고 신호 단어({len(hits)}개): {', '.join(hits)}")
    print(f"OCR 채택 기준 통과(길이 {args.min_chars}↑ + 신호 3개↑): "
          f"{ocr_text_is_usable(text, args.min_chars)}")
    print(f"[참고] 정식 라벨 엄격기준(담당업무+자격요건): {has_complete_text_detail(text)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", choices=sorted(SITES), help="OCR 보강할 사이트")
    parser.add_argument("--json", type=Path, help="입력 JSON 직접 지정(사이트 대신)")
    parser.add_argument("--db", type=Path, help="DB 경로 직접 지정")
    parser.add_argument("--out", type=Path, help="결과 JSON 저장 경로(기본: 입력_ocr.json)")
    parser.add_argument("--in-place", action="store_true",
                        help="원본 JSON/DB를 직접 갱신(해당 사이트 크롤러 종료 후에만!)")
    parser.add_argument("--max", type=int, default=0,
                        help="이번 실행에서 OCR 시도할 최대 공고 수(0=제한없음)")
    parser.add_argument("--delay", type=float, default=0.5, help="이미지 요청 간격(초)")
    parser.add_argument("--checkpoint-every", type=int, default=10,
                        help="이 수만큼 채택될 때마다 중간 저장")
    parser.add_argument("--min-chars", type=int, default=400,
                        help="OCR 결과 채택 최소 글자 수(공백 제외)")
    parser.add_argument("--slice-height", type=int, default=2000,
                        help="이보다 세로가 길면 잘라서 OCR")
    parser.add_argument("--overlap", type=int, default=150, help="슬라이스 겹침(px)")
    parser.add_argument("--gpu", action="store_true", help="GPU 사용(CUDA 있을 때)")
    parser.add_argument("--engine", choices=["auto", "paddle", "easy"], default="auto",
                        help="OCR 엔진(기본 auto: PaddleOCR 우선, 불가 시 EasyOCR)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="이전에 실패로 기록된 공고도 다시 시도")
    parser.add_argument("--test-url", help="이미지 URL 하나만 OCR 해서 출력(확인용)")
    args = parser.parse_args()

    if args.test_url:
        return run_test_url(args)

    if not args.site and not args.json:
        raise SystemExit("--site 또는 --json 중 하나는 지정해야 합니다(또는 --test-url).")

    if args.site:
        in_json, in_db = SITES[args.site]
    else:
        in_json, in_db = args.json, args.db
    if not in_json or not in_json.exists():
        raise SystemExit(f"입력 JSON을 찾을 수 없습니다: {in_json}")

    out_json = in_json if args.in_place else (args.out or in_json.with_name(in_json.stem + "_ocr.json"))
    out_db = in_db if args.in_place else (out_json.with_suffix(".db"))
    sidecar = in_json.with_name(in_json.stem + "_ocr_failed.json")

    # 이미 진행분이 있으면(_ocr.json) 이어서, 아니면 원본에서 시작
    rows = load_existing_rows(out_json) if out_json.exists() else load_existing_rows(in_json)
    failed = set() if args.retry_failed else load_failed(sidecar)

    targets = [r for r in rows
               if r.get("need_ocr") == "O"
               and r.get("image_urls")
               and str(r.get("posting_id")) not in failed]
    total_o = sum(r.get("need_ocr") == "O" for r in rows)
    print(f"[ocr] site={args.site or in_json.stem} 전체={len(rows)} 이미지형(O)={total_o} "
          f"이번대상={len(targets)} (실패제외={len(failed)}) out={out_json}", flush=True)

    accepted = 0
    tried = 0
    for row in targets:
        if args.max and tried >= args.max:
            break
        tried += 1
        pid = str(row.get("posting_id"))
        try:
            text = ocr_posting(row["image_urls"], args.gpu, args.slice_height, args.overlap,
                               args.delay, args.engine)
            text = fix_common_ocr(clean_multiline(text))
            if ocr_text_is_usable(text, args.min_chars):
                row["detail_text"] = text
                row["need_ocr"] = "X"
                accepted += 1
                print(f"[ocr] {tried}/{len(targets)} pid={pid} status=filled chars={len(text)} "
                      f"title={row.get('title','')[:35]!r}", flush=True)
                if accepted % args.checkpoint_every == 0:
                    save(rows, out_json, out_db)
                    print(f"[ocr] status=checkpoint accepted={accepted}", flush=True)
            else:
                failed.add(pid)
                print(f"[ocr] {tried}/{len(targets)} pid={pid} status=insufficient chars={len(text)}",
                      flush=True)
        except Exception as exc:
            failed.add(pid)
            print(f"[ocr] {tried}/{len(targets)} pid={pid} status=error error={type(exc).__name__}",
                  flush=True)

    save(rows, out_json, out_db)
    save_failed(sidecar, failed)
    remaining = sum(r.get("need_ocr") == "O" for r in rows)
    print(f"[ocr] status=completed tried={tried} filled={accepted} 남은O={remaining} "
          f"json={out_json} db={out_db}", flush=True)
    return 0


def clean_multiline(text: str) -> str:
    """빈 줄을 정리하고 앞뒤 공백을 제거한다."""
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


if __name__ == "__main__":
    raise SystemExit(main())
