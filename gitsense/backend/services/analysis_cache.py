import hashlib
import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.models.report import Report
from backend.models.commit import Commit
from backend.services.redis_client import get_redis_client

logger = logging.getLogger(__name__)

REDIS_CACHE_TTL = 86400  # 24 hours


def compute_diff_hash(repo_full_name: str, full_diff: str) -> str:
    """
    Computes a deterministic, SHA-256 fingerprint from the repository name and
    normalized commit diff text.
    """
    normalized_repo = repo_full_name.lower().strip()
    normalized_diff = "\n".join(line.rstrip() for line in full_diff.strip().splitlines())
    raw_key = f"{normalized_repo}:{normalized_diff}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def get_cached_report_redis(repo_id: int, diff_hash: str) -> dict | None:
    """
    L1 Cache: Tries to fetch pre-computed report JSON from Redis (< 0.5ms).
    Returns None if cache miss or if Redis is unavailable.
    """
    if not diff_hash:
        return None

    client = get_redis_client()
    if client is None:
        return None

    cache_key = f"gitsense:llm_cache:{repo_id}:{diff_hash}"
    try:
        data = await client.get(cache_key)
        if data:
            logger.info(f"⚡ [Redis L1 Cache Hit] Found cached report for key {cache_key}")
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Redis L1 lookup failed ({e}), falling back to PostgreSQL DB.")
        return None

    return None


async def set_cached_report_redis(repo_id: int, diff_hash: str, report_dict: dict) -> None:
    """
    L1 Cache: Stores structured report JSON in Redis with 24h expiration.
    Fails silently if Redis is unavailable.
    """
    if not diff_hash or not report_dict:
        return

    client = get_redis_client()
    if client is None:
        return

    cache_key = f"gitsense:llm_cache:{repo_id}:{diff_hash}"
    try:
        payload = json.dumps(report_dict)
        await client.set(cache_key, payload, ex=REDIS_CACHE_TTL)
        logger.debug(f"Stored report in Redis L1 cache with key {cache_key}")
    except Exception as e:
        logger.warning(f"Failed to store report in Redis L1 cache ({e}).")


async def find_cached_report(db: AsyncSession, repo_id: int, diff_hash: str) -> Report | None:
    """
    L2 Cache: Queries PostgreSQL database for a previously completed Report
    matching the given repo_id and diff_hash (durable fallback).
    """
    if not diff_hash:
        return None

    query = (
        select(Report)
        .join(Commit, Commit.id == Report.commit_id)
        .where(
            Commit.repo_id == repo_id,
            Report.diff_hash == diff_hash,
            Commit.status == "completed",
        )
        .order_by(Report.created_at.desc())
        .limit(1)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()
