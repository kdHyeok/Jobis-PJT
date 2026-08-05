"""pgvector 저장 — postings/chunks UPSERT + content_hash 기반 재임베딩 스킵.

배치에서 사라진 공고는 삭제하지 않고 is_active=false로만 표시
(평가 스냅샷 재현성 — CRAG_평가계획 §1 동결 스냅샷 원칙과 동일 이유).
단, 비활성화 범위는 이번 배치에 포함된 source로 한정한다. 소스별 파일이
따로 들어오므로 전역 비활성화는 다른 소스를 통째로 검색에서 지워버린다.
"""
from __future__ import annotations

import os

import psycopg
from psycopg.types.json import Jsonb

from .embedding import content_hash
from .model_config import LOCAL_EMBED_MODEL, VECTOR_DIMENSIONS, get_model_settings
from .schema import Chunk, Posting


def get_dsn() -> str:
    from dotenv import load_dotenv
    load_dotenv()
    dsn = os.environ.get("PG_DSN")
    if not dsn:
        raise RuntimeError("PG_DSN not set (.env)")
    return dsn


def connect():
    return psycopg.connect(get_dsn())


def get_index_profile(conn) -> tuple[str, str, int] | None:
    """Return the embedding profile recorded for the currently stored index."""

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT embed_provider, embed_model, embed_dimensions
            FROM rag_index_metadata
            WHERE singleton
            """
        )
        row = cur.fetchone()
    return (str(row[0]), str(row[1]), int(row[2])) if row else None


def _target_index_profile() -> tuple[str, str, int]:
    settings = get_model_settings()
    return (
        settings.embed_provider,
        settings.embed_model,
        settings.vector_dimensions,
    )


def ensure_index_compatible(conn) -> None:
    """Refuse searches that would mix incompatible embedding vector spaces."""

    settings = get_model_settings()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")
        embedded = int(cur.fetchone()[0])
    if embedded == 0:
        return

    try:
        current = get_index_profile(conn)
    except Exception:
        # Pre-Flyway local databases used BGE-M3 and can still be searched safely
        # with the unchanged default. GMS must wait for the metadata migration.
        if settings.uses_legacy_local_embedding:
            return
        raise

    expected = _target_index_profile()
    if current is None and settings.uses_legacy_local_embedding:
        return
    if current != expected:
        actual = "missing" if current is None else "/".join(map(str, current))
        wanted = "/".join(map(str, expected))
        raise RuntimeError(
            "RAG index embedding profile mismatch: "
            f"database={actual}, runtime={wanted}. "
            "Run the jobis_rag ingestion successfully before serving searches."
        )


def _record_index_profile(cur) -> None:
    settings = get_model_settings()
    cur.execute(
        """
        INSERT INTO rag_index_metadata (
            singleton, embed_provider, embed_model, embed_dimensions, updated_at
        )
        VALUES (true, %s, %s, %s, now())
        ON CONFLICT (singleton) DO UPDATE SET
            embed_provider=EXCLUDED.embed_provider,
            embed_model=EXCLUDED.embed_model,
            embed_dimensions=EXCLUDED.embed_dimensions,
            updated_at=now()
        """,
        (
            settings.embed_provider,
            settings.embed_model,
            settings.vector_dimensions,
        ),
    )


def existing_hashes(conn, chunk_ids: list[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_id, content_hash FROM chunks WHERE chunk_id = ANY(%s)",
            (chunk_ids,),
        )
        return dict(cur.fetchall())


def unchanged_chunk_ids(conn, chunks: list[Chunk]) -> set[str]:
    """내용이 그대로인 청크 id. 임베딩 '전에' 호출해야 재임베딩 비용이 실제로 준다."""
    hashes = {c.chunk_id: content_hash(c.text) for c in chunks}
    prior = existing_hashes(conn, list(hashes))
    return {cid for cid, h in hashes.items() if prior.get(cid) == h}


def upsert_postings(conn, postings: list[Posting], raw_by_uid: dict[str, dict],
                    deactivate_missing: bool = True) -> dict:
    """이번 배치의 공고를 UPSERT하고, 같은 source에서 사라진 공고만 비활성화.

    deactivate_missing=False로 두면 어떤 공고도 비활성화하지 않는다
    (한 소스를 여러 파일로 쪼개 넣는 경우처럼 배치가 부분집합일 때 사용).
    """
    sources = sorted({p.source for p in postings})
    uids = [p.uid for p in postings]
    deactivated = 0
    with conn.cursor() as cur:
        for p in postings:
            cur.execute(
                """
                INSERT INTO postings (uid, posting_id, source, company, title, url,
                    employment_type, exp_min, exp_max, regions, location_raw, deadline, tech,
                    role_category, needs_review, is_active, collected_at, raw, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, true, %s, %s, now())
                ON CONFLICT (uid) DO UPDATE SET
                    posting_id=EXCLUDED.posting_id, source=EXCLUDED.source,
                    company=EXCLUDED.company, title=EXCLUDED.title,
                    url=EXCLUDED.url, employment_type=EXCLUDED.employment_type,
                    exp_min=EXCLUDED.exp_min, exp_max=EXCLUDED.exp_max, regions=EXCLUDED.regions,
                    location_raw=EXCLUDED.location_raw,
                    deadline=EXCLUDED.deadline, tech=EXCLUDED.tech,
                    role_category=EXCLUDED.role_category,
                    needs_review=EXCLUDED.needs_review, is_active=true,
                    collected_at=EXCLUDED.collected_at, raw=EXCLUDED.raw,
                    updated_at=now()
                """,
                (p.uid, p.posting_id, p.source, p.company, p.title, p.url,
                 p.employment_type, p.exp_min, p.exp_max, p.regions, p.location_raw,
                 p.deadline, p.tech, p.role_category or None,
                 p.needs_review, p.collected_at, Jsonb(raw_by_uid.get(p.uid, {}))),
            )
        if deactivate_missing and sources:
            cur.execute(
                """
                UPDATE postings SET is_active = false, updated_at = now()
                WHERE source = ANY(%s) AND NOT (uid = ANY(%s)) AND is_active
                """,
                (sources, uids),
            )
            deactivated = cur.rowcount
    conn.commit()
    return {"upserted": len(postings), "sources": sources, "deactivated": deactivated}


def delete_orphan_chunks(
    conn,
    posting_uids: list[str],
    live_chunk_ids: list[str],
    *,
    commit: bool = True,
) -> int:
    """이번 배치 공고에 속하지만 현재 청크 집합에 없는 청크 제거.

    공고 본문이 짧아지면 청크 수가 줄어드는데, UPSERT만으로는 예전 청크가
    남아 낡은 내용이 계속 검색된다.
    """
    if not posting_uids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM chunks WHERE posting_uid = ANY(%s) AND NOT (chunk_id = ANY(%s))",
            (posting_uids, live_chunk_ids),
        )
        deleted = cur.rowcount
    if commit:
        conn.commit()
    return deleted


def upsert_chunks(conn, chunks: list[Chunk], embeddings: list[list[float] | None]) -> dict:
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"chunks/embeddings length mismatch: {len(chunks)} != {len(embeddings)}"
        )
    written, skipped_no_embed = 0, 0
    hashes = {c.chunk_id: content_hash(c.text) for c in chunks}

    # Serialize ingestion transactions so two schedulers cannot publish
    # different embedding profiles concurrently.
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("jobrag-index",))

    prior = existing_hashes(conn, list(hashes))
    target_profile = _target_index_profile()
    current_profile = get_index_profile(conn)

    # Databases created before the metadata row existed can only contain
    # vectors from the original local BGE-M3 implementation. Infer that
    # profile so a first switch to GMS receives the same full-reindex guard.
    if current_profile is None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM chunks c
                    JOIN postings p ON p.uid = c.posting_uid
                    WHERE p.is_active AND c.embedding IS NOT NULL
                )
                """
            )
            has_active_embeddings = bool(cur.fetchone()[0])
        if has_active_embeddings:
            current_profile = ("local", LOCAL_EMBED_MODEL, VECTOR_DIMENSIONS)

    switching_profile = current_profile not in (None, target_profile)
    posting_uids = sorted({c.posting_uid for c in chunks})
    live_chunk_ids = [c.chunk_id for c in chunks]

    if switching_profile:
        # Updating only part of the active corpus would mix two vector spaces.
        # Old chunks belonging to incoming postings are safe because they are
        # removed in the same transaction below.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(DISTINCT c.posting_uid)
                FROM chunks c
                JOIN postings p ON p.uid = c.posting_uid
                WHERE p.is_active
                  AND c.embedding IS NOT NULL
                  AND NOT (c.posting_uid = ANY(%s))
                """,
                (posting_uids,),
            )
            uncovered_postings = int(cur.fetchone()[0])
        if uncovered_postings:
            conn.rollback()
            raise RuntimeError(
                "Embedding provider/model changed, but the ingestion input does "
                f"not cover {uncovered_postings} active postings. Run a full RAG "
                "export and ingestion before changing the index profile."
            )

    with conn.cursor() as cur:
        for c, emb in zip(chunks, embeddings):
            h = hashes[c.chunk_id]
            if prior.get(c.chunk_id) == h:
                continue  # 내용 불변 -> 스킵 (임베딩도 이미 있음)
            if emb is None:
                skipped_no_embed += 1
                continue
            cur.execute(
                """
                INSERT INTO chunks (chunk_id, posting_uid, part, text, tokens,
                    content_hash, forced_split, needs_review, embedding, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (chunk_id) DO UPDATE SET
                    posting_uid=EXCLUDED.posting_uid, part=EXCLUDED.part,
                    text=EXCLUDED.text, tokens=EXCLUDED.tokens,
                    content_hash=EXCLUDED.content_hash, forced_split=EXCLUDED.forced_split,
                    needs_review=EXCLUDED.needs_review, embedding=EXCLUDED.embedding,
                    updated_at=now()
                """,
                (c.chunk_id, c.posting_uid, c.part, c.text, c.tokens,
                 h, c.forced_split, c.needs_review, emb),
            )
            written += 1

        # A provider switch changes every content hash. Do not publish a mixed
        # vector space when even one replacement embedding failed.
        if switching_profile and skipped_no_embed:
            conn.rollback()
            raise RuntimeError(
                "Embedding provider/model changed but some replacement vectors "
                "failed; the index update was rolled back"
            )

    # Orphan cleanup and profile publication must be atomic with vector writes.
    # Otherwise a search could briefly observe old and new vector spaces.
    orphans = delete_orphan_chunks(
        conn,
        posting_uids,
        live_chunk_ids,
        commit=False,
    )
    with conn.cursor() as cur:
        _record_index_profile(cur)
    conn.commit()

    unchanged = len(chunks) - written - skipped_no_embed
    return {"written": written, "skipped_unchanged": unchanged,
            "skipped_no_embedding": skipped_no_embed,
            "orphans_deleted": orphans,
            "skip_ratio": round(unchanged / len(chunks), 3) if chunks else 0.0}
