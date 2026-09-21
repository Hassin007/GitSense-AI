"""
Incremental, self-correcting dependency graph. Every time a file is
analyzed, its COMPLETE current set of local-import edges is synced —
stale edges removed, current edges upserted — rather than only ever
appended to. Reuses the exact resolution logic already built for
cross-file context extraction.

Coverage is a LOWER BOUND: only files that have actually been analyzed
contribute edges. Always presented to the LLM as such.
"""

import logging
import asyncio
from sqlalchemy import select, delete
from backend.database import AsyncSessionLocal
from backend.models.file_dependency import FileDependency
from backend.services.cross_file_resolver import (
    parse_imports_from_source, is_local_import, resolve_candidate_paths
)
from backend.services.github import fetch_first_existing_file, get_github_client

logger = logging.getLogger(__name__)

MAX_IMPORTS_RESOLVED_PER_FILE = 8


async def sync_file_dependencies(
    repo_id: int, filepath: str, full_file_content: str, extension: str,
    github_pat: str, repo_full_name: str, commit_sha: str,
) -> None:
    """
    Fully syncs this file's outgoing dependency edges against its
    CURRENT complete import list. Deletes edges no longer present,
    upserts edges that are. Call this every time a file is analyzed.
    """
    all_refs = parse_imports_from_source(full_file_content, extension)
    local_refs = [r for r in all_refs if is_local_import(r)]

    if len(local_refs) > MAX_IMPORTS_RESOLVED_PER_FILE:
        logger.info(f"[dep-graph] {filepath} has {len(local_refs)} local imports, "
                     f"capping resolution at {MAX_IMPORTS_RESOLVED_PER_FILE}")
        local_refs = local_refs[:MAX_IMPORTS_RESOLVED_PER_FILE]

    current_edges: set[str] = set()

    for ref in local_refs:
        candidates = resolve_candidate_paths(filepath, ref.module_path, extension)
        if not candidates:
            continue
        resolved_path, content = await fetch_first_existing_file(
            github_pat, repo_full_name, commit_sha, candidates
        )
        if resolved_path:
            current_edges.add(resolved_path)
        # unresolved imports are simply not added as edges — this graph
        # only tracks CONFIRMED file-to-file edges, broken-import
        # signaling is already handled separately by cross_file_resolver

    async with AsyncSessionLocal() as db:
        # Full sync: delete every existing edge for this importer, then
        # re-insert the current set. Simpler and safer than diffing old
        # vs new edge-by-edge, and this only runs once per analyzed file.
        await db.execute(
            delete(FileDependency).where(
                FileDependency.repo_id == repo_id,
                FileDependency.importer_filepath == filepath,
            )
        )
        for imported_path in current_edges:
            db.add(FileDependency(
                repo_id=repo_id, importer_filepath=filepath,
                imported_filepath=imported_path, last_seen_commit_sha=commit_sha,
            ))
        await db.commit()

    if current_edges:
        logger.info(f"[dep-graph] Synced {filepath}: {len(current_edges)} known outgoing edge(s)")


async def get_known_importers(repo_id: int, filepath: str) -> list[str]:
    """
    Reverse lookup: which analyzed files are known to import this file?
    This is a LOWER BOUND — only reflects files that have themselves
    been analyzed and had their edges synced.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(FileDependency.importer_filepath).where(
                FileDependency.repo_id == repo_id,
                FileDependency.imported_filepath == filepath,
            )
        )
        return [row[0] for row in result.all()]


async def get_transitive_importers(repo_id: int, filepath: str, max_depth: int = 3) -> dict[str, int]:
    """
    Multi-hop reverse lookup: returns a dict of {importer_filepath: depth}
    representing direct (depth=1) and transitive (depth=2..max_depth)
    importers of the given filepath.
    """
    visited: dict[str, int] = {}
    current_level = [filepath]

    async with AsyncSessionLocal() as db:
        for depth in range(1, max_depth + 1):
            if not current_level:
                break
            result = await db.execute(
                select(FileDependency.importer_filepath, FileDependency.imported_filepath).where(
                    FileDependency.repo_id == repo_id,
                    FileDependency.imported_filepath.in_(current_level),
                )
            )
            next_level = []
            for row in result.all():
                importer = row[0]
                if importer not in visited and importer != filepath:
                    visited[importer] = depth
                    next_level.append(importer)
            current_level = next_level

    return visited


async def _index_single_file(
    repo_id: int, path: str, github_pat: str, repo_full_name: str, branch: str, semaphore: asyncio.Semaphore
) -> bool:
    async with semaphore:
        ext = "." + path.rsplit(".", 1)[-1]
        _, content = await fetch_first_existing_file(github_pat, repo_full_name, branch, [path])
        if content:
            await sync_file_dependencies(repo_id, path, content, ext, github_pat, repo_full_name, branch)
            return True
        return False


async def index_repository_dependencies(
    repo_id: int, repo_full_name: str, github_pat: str, branch: str
) -> int:
    """
    Background job: fetches repo file tree and pre-indexes outgoing import
    edges for all code files to build a comprehensive dependency graph.
    """
    client = get_github_client()
    headers = {"Accept": "application/vnd.github+json"}
    if github_pat:
        headers["Authorization"] = f"Bearer {github_pat}"

    r = await client.get(
        f"https://api.github.com/repos/{repo_full_name}/git/trees/{branch}?recursive=1",
        headers=headers,
    )
    if r.status_code != 200:
        logger.warning(f"[dep-graph] Failed to fetch git tree for {repo_full_name}: {r.status_code}")
        return 0

    tree = r.json().get("tree", [])
    valid_exts = {".py", ".js", ".jsx", ".ts", ".tsx"}
    code_files = [item["path"] for item in tree if item.get("type") == "blob" and any(item["path"].endswith(ext) for ext in valid_exts)]

    # Limit initial scan cap to top 50 code files to respect API limits
    code_files = code_files[:50]

    semaphore = asyncio.Semaphore(5)
    tasks = [
        _index_single_file(repo_id, path, github_pat, repo_full_name, branch, semaphore)
        for path in code_files
    ]
    results = await asyncio.gather(*tasks)
    synced_count = sum(1 for res in results if res)

    logger.info(f"[dep-graph] Pre-indexed {synced_count} files for {repo_full_name}")
    return synced_count

