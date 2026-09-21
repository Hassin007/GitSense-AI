"""
Redis-backed analysis task queue with two priority lanes.

Keys:
  gitsense:queue:high   — single-commit incremental pushes + retries
  gitsense:queue:low    — coalesced final commit from bulk pushes

Tasks are JSON-serialized dicts:
  {"type": "analyze", "repo_id": int, "commit_id": int}
  {"type": "retry",   "repo_id": int, "commit_id": int}
"""
import json
import logging
import asyncio
from backend.services.redis_client import get_redis_client

logger = logging.getLogger(__name__)

QUEUE_KEY_HIGH = "gitsense:queue:high"
QUEUE_KEY_LOW = "gitsense:queue:low"
MAX_QUEUE_DEPTH = 10
MAX_CONCURRENT_ANALYSES = 3

# Module-level semaphore — shared across all consumer coroutines
_analysis_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)


async def enqueue_analysis(
    repo_id: int,
    commit_id: int,
    priority: str = "high",
    task_type: str = "analyze"
) -> bool:
    """
    Enqueue an analysis task. Returns True if enqueued, False if rejected
    or if Redis is unavailable.
    """
    client = get_redis_client()
    if client is None:
        logger.warning("[queue] Redis unavailable — returning False for fallback execution.")
        return False

    queue_key = QUEUE_KEY_HIGH if priority == "high" else QUEUE_KEY_LOW

    try:
        # Hard rejection if total queue depth exceeds MAX_QUEUE_DEPTH
        high_len = await client.llen(QUEUE_KEY_HIGH)
        low_len = await client.llen(QUEUE_KEY_LOW)
        if (high_len + low_len) >= MAX_QUEUE_DEPTH:
            logger.error(
                f"[queue] Rejected: queue full ({high_len}H + {low_len}L >= {MAX_QUEUE_DEPTH}). "
                f"Commit {commit_id} stays as 'pending' for stale recovery."
            )
            return False

        task = json.dumps({"type": task_type, "repo_id": repo_id, "commit_id": commit_id})
        await client.rpush(queue_key, task)
        logger.info(
            f"[queue] Enqueued {task_type} for commit {commit_id} "
            f"(priority={priority}, depth={high_len + low_len + 1})"
        )
        return True
    except Exception as e:
        logger.error(f"[queue] Redis enqueue error: {e}")
        return False


async def dequeue_task() -> dict | None:
    """
    Dequeue next task. HIGH priority is always drained first.
    Returns parsed task dict, or None if both queues are empty or Redis fails.
    """
    client = get_redis_client()
    if client is None:
        return None

    try:
        # Try HIGH first, then LOW
        raw = await client.lpop(QUEUE_KEY_HIGH)
        if raw is None:
            raw = await client.lpop(QUEUE_KEY_LOW)
        if raw is None:
            return None

        return json.loads(raw)
    except Exception as e:
        logger.error(f"[queue] Redis dequeue error: {e}")
        return None


def get_analysis_semaphore() -> asyncio.Semaphore:
    """Return the global analysis concurrency semaphore."""
    return _analysis_semaphore
