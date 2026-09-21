import hashlib
import logging
from backend.services.redis_client import redis_get_json, redis_set_json

logger = logging.getLogger(__name__)

CURRENT_AST_VERSION = 1


def git_blob_sha(content: str) -> str:
    """
    Computes standard Git blob SHA-1 for file content text.
    Formula: sha1("blob {byte_length}\0{content_bytes}")
    Determined strictly by content — identical file text always produces identical SHA.
    """
    data = content.encode("utf-8")
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


async def get_cached_ast(blob_sha: str) -> dict | None:
    """
    Fetches pre-extracted AST metadata from Redis keyed by blob_sha.
    Returns dict with keys 'signatures' and 'exported_symbols', or None if miss/stale version.
    """
    if not blob_sha:
        return None

    key = f"ts_ast:{blob_sha}"
    data = await redis_get_json(key)
    if isinstance(data, dict):
        if data.get("ast_version") == CURRENT_AST_VERSION:
            logger.debug(f"⚡ [AST Cache Hit] Reusing Tree-sitter metadata for blob {blob_sha[:10]}")
            return data
        else:
            logger.debug(f"Stale AST version in cache for blob {blob_sha[:10]}")
            return None
    return None


async def set_cached_ast(blob_sha: str, signatures: list[dict], exported_symbols: list[dict]) -> None:
    """
    Caches extracted AST metadata in Redis under blob_sha with no expiration (immutable).
    """
    if not blob_sha:
        return

    key = f"ts_ast:{blob_sha}"
    payload = {
        "signatures": signatures,
        "exported_symbols": exported_symbols,
        "ast_version": CURRENT_AST_VERSION,
    }
    # No TTL passed since blob SHA is content-addressable and immutable
    await redis_set_json(key, payload)
