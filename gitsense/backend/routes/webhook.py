from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db, AsyncSessionLocal
from backend.models.repo import ConnectedRepo
from backend.models.commit import Commit
from backend.models.report import Report
from backend.services.dependency_graph import sync_file_dependencies, get_known_importers, get_transitive_importers
from backend.services.blast_radius_builder import generate_blast_radius_mermaid
from backend.services.interface_tracker import INTERFACE_TRACKED_EXTENSIONS
from backend.services.security import verify_github_signature, decrypt_pat
from backend.services.github import fetch_commit_diff
from backend.services.analysis_graph import analysis_graph
from backend.services.notifications import (
    create_notifications_for_multiagent_report, create_failure_notification
)
from datetime import datetime, timezone
import asyncio
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    verify_github_signature(body, signature)

    payload = await request.json()
    event_type = request.headers.get("X-GitHub-Event", "")

    if event_type != "push":
        return {"status": "ignored", "reason": f"Event type '{event_type}' not handled."}

    repo_full_name = payload.get("repository", {}).get("full_name")
    ref = payload.get("ref", "")
    commits = payload.get("commits", [])

    if not commits:
        return {"status": "ignored", "reason": "No commits in payload."}

    result = await db.execute(
        select(ConnectedRepo).where(ConnectedRepo.repo_full_name == repo_full_name)
    )
    repo = result.scalar_one_or_none()

    if not repo:
        return {"status": "ignored", "reason": "Repository not registered in GitSense."}

    branch_from_ref = ref.replace("refs/heads/", "")
    if branch_from_ref != repo.branch:
        return {"status": "ignored", "reason": f"Push to '{branch_from_ref}', monitoring '{repo.branch}'."}

    background_tasks.add_task(process_push_event, payload, repo.id)

    return {"status": "received", "commits": len(commits)}


async def process_push_event(payload: dict, repo_id: int):
    """
    Background task: stores each commit, then immediately runs the full
    analysis pipeline on it (Decision 1: Option A — no separate worker).

    Uses its own DB session since background tasks outlive the request's
    session lifecycle.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ConnectedRepo).where(ConnectedRepo.id == repo_id))
        repo = result.scalar_one_or_none()
        if not repo:
            logger.error(f"Repo {repo_id} not found during background processing.")
            return

        commits_data = payload.get("commits", [])
        if not commits_data:
            return

        # Detect initial push: no prior processed commits for this repo
        prior_check = await db.execute(
            select(Commit.id).where(
                Commit.repo_id == repo_id,
                Commit.status.in_(["completed", "baseline", "skipped"])
            ).limit(1)
        )
        is_initial_push = prior_check.scalar_one_or_none() is None

        if is_initial_push:
            logger.info(f"[baseline] Initial push detected for repo {repo.repo_full_name} "
                        f"({len(commits_data)} commits) — skipping LLM analysis, indexing only")

            # Store all intermediate commits as baseline (no Report)
            for commit_data in commits_data[:-1]:
                commit = await _store_commit(db, repo, commit_data)
                commit.status = "baseline"
                commit.status_detail = "Initial push — baseline indexed with final commit"
                commit.risk_score = 0.0
                await db.commit()

            # Baseline-index the final commit only (no Report)
            final_commit = await _store_commit(db, repo, commits_data[-1])
            try:
                await _baseline_index_commit(db, repo, final_commit)
            except Exception as e:
                logger.error(f"[baseline] Failed to index: {e}", exc_info=True)
                try:
                    await db.rollback()
                    final_commit.status = "failed"
                    final_commit.status_detail = f"Baseline indexing failed: {type(e).__name__}: {str(e)[:200]}"
                    await db.commit()
                except Exception as db_err:
                    logger.error(f"[baseline] Could not record failure: {db_err}")
            return

        # ── Non-initial push ──────────────────────────────────────────
        from backend.services.analysis_queue import enqueue_analysis

        if len(commits_data) > 1:
            final_sha_short = commits_data[-1].get("id", "unknown")[:7]
            logger.info(f"[coalesce] Non-initial bulk push detected for {repo.repo_full_name} "
                        f"({len(commits_data)} commits) — coalescing to final commit {final_sha_short}")

            # Coalesce intermediate commits: status='coalesced' (no Report)
            for commit_data in commits_data[:-1]:
                commit = await _store_commit(db, repo, commit_data)
                commit.status = "coalesced"
                commit.status_detail = f"Bulk push — analyzed with final commit {final_sha_short}"
                commit.risk_score = 0.0
                await db.commit()

            final_commit = await _store_commit(db, repo, commits_data[-1])
            enqueued = await enqueue_analysis(repo.id, final_commit.id, priority="low")
            if not enqueued:
                logger.info(f"[queue] Enqueue skipped/failed for {final_commit.sha[:7]} — fallback to direct execution")
                await _execute_single_analysis(db, repo, final_commit)
        else:
            commit = await _store_commit(db, repo, commits_data[0])
            enqueued = await enqueue_analysis(repo.id, commit.id, priority="high")
            if not enqueued:
                logger.info(f"[queue] Enqueue skipped/failed for {commit.sha[:7]} — fallback to direct execution")
                await _execute_single_analysis(db, repo, commit)


async def _execute_single_analysis(db: AsyncSession, repo: ConnectedRepo, commit: Commit):
    """Direct analysis execution (fallback when Redis unavailable or queue full)."""
    commit_sha = commit.sha[:7] if commit.sha else "unknown"
    try:
        await _analyze_commit(db, repo, commit)
    except Exception as e:
        logger.error(f"[process_push_event] Unhandled exception analyzing "
                     f"{commit_sha}: {e}", exc_info=True)
        try:
            await db.rollback()
            commit.status = "failed"
            commit.status_detail = f"Internal error during analysis: {type(e).__name__}: {str(e)[:200]}"
            await db.commit()
        except Exception as db_error:
            logger.error(f"[process_push_event] Could not record failure "
                         f"status for {commit_sha}: {db_error}")


MAX_BASELINE_INTERFACE_FILES = 50


async def _baseline_index_commit(db: AsyncSession, repo: ConnectedRepo, commit: Commit):
    """
    Index-only path for initial pushes. Zero LLM calls, no Report creation.

    Phase 1: Dependency graph — delegates to index_repository_dependencies()
             which handles up to 50 files with built-in concurrency.
    Phase 2: Interface fingerprinting — concurrent compute_interface_changes()
             for files in the diff, capped at MAX_BASELINE_INTERFACE_FILES.
    """
    await _update_status(db, commit, "analyzing", "Initial push — building baseline index")
    pat = decrypt_pat(repo.github_pat)

    try:
        full_diff = await fetch_commit_diff(pat, repo.repo_full_name, commit.sha)
    except Exception as e:
        commit.skip_reason = f"Could not fetch diff: {e}"
        await _update_status(db, commit, "failed", "diff fetch failed")
        return

    # ── Phase 1: Dependency Graph (repo-wide, concurrent) ──────────────
    from backend.services.dependency_graph import index_repository_dependencies

    deps_synced = 0
    try:
        deps_synced = await index_repository_dependencies(
            repo.id, repo.repo_full_name, pat, repo.branch
        )
    except Exception as idx_e:
        logger.warning(f"[baseline] Dependency indexing warning: {idx_e}")

    # ── Phase 2: Interface Fingerprinting (diff files, concurrent) ─────
    from backend.services.analysis_graph import extract_file_chunks, compute_interface_changes
    from backend.services.file_classifier import (
        classify_file, FileTier, INTERFACE_TRACKED_EXTENSIONS,
    )
    from backend.services.github import fetch_file_content

    raw_chunks = extract_file_chunks(full_diff)

    interface_files: list[tuple[str, str]] = []  # (filepath, extension)
    for filepath in raw_chunks:
        tier = classify_file(filepath)
        if tier != FileTier.FULL:
            continue
        ext = "." + filepath.rsplit(".", 1)[-1] if "." in filepath else ""
        if ext in INTERFACE_TRACKED_EXTENSIONS:
            interface_files.append((filepath, ext))

    interface_files = interface_files[:MAX_BASELINE_INTERFACE_FILES]

    semaphore = asyncio.Semaphore(5)

    async def _fingerprint_file(filepath: str, ext: str) -> bool:
        async with semaphore:
            content = await fetch_file_content(
                pat, repo.repo_full_name, filepath, commit.sha
            )
            if not content:
                return False
            await compute_interface_changes(
                repo.id, filepath, content, ext,
                pat, repo.repo_full_name, commit.sha
            )
            return True

    results = await asyncio.gather(
        *[_fingerprint_file(fp, ext) for fp, ext in interface_files],
        return_exceptions=True,
    )
    interfaces_cached = sum(1 for r in results if r is True)
    errors = [r for r in results if isinstance(r, Exception)]
    if errors:
        logger.warning(f"[baseline] {len(errors)} interface fingerprinting errors (non-fatal)")

    # ── Mark complete (no Report) ───────────────────────────────────────
    commit.risk_score = 0.0
    await _update_status(db, commit, "baseline",
                         f"Initial push — {deps_synced} dep edges, {interfaces_cached} interfaces indexed")

    logger.info(
        f"[baseline] {repo.repo_full_name}: {deps_synced} dep edges, "
        f"{interfaces_cached} interfaces — 0 LLM calls"
    )


async def _store_commit(db: AsyncSession, repo: ConnectedRepo, commit_data: dict) -> Commit:
    sha = commit_data.get("id")
    message = commit_data.get("message", "")
    author = commit_data.get("author", {}).get("name", "unknown")
    timestamp_str = commit_data.get("timestamp")

    try:
        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        timestamp = datetime.now(timezone.utc).replace(tzinfo=None)

    commit = Commit(
        repo_id=repo.id, sha=sha, message=message, author=author,
        timestamp=timestamp, status="pending",
    )
    db.add(commit)
    await db.commit()
    await db.refresh(commit)
    return commit


async def _update_status(db: AsyncSession, commit: Commit, status: str, detail: str = None):
    try:
        commit.status = status
        commit.status_detail = detail
        commit.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
    except Exception as e:
        logger.warning(f"[status-update] Could not update status to '{status}' for commit {getattr(commit, 'sha', 'unknown')[:7]}: {e}")
        try:
            await db.rollback()
        except Exception:
            pass


async def _analyze_commit(db: AsyncSession, repo: ConnectedRepo, commit: Commit):
    await _update_status(db, commit, "analyzing")

    pat = decrypt_pat(repo.github_pat)

    try:
        full_diff = await fetch_commit_diff(pat, repo.repo_full_name, commit.sha)
    except Exception as e:
        commit.skip_reason = f"Could not fetch diff: {e}"
        await _update_status(db, commit, "failed", "diff fetch failed")
        await create_failure_notification(db, commit.id, commit.skip_reason)
        return

    # Check 2-Tier LLM Diff-Hash Cache before invoking multi-agent graph
    from backend.services.analysis_cache import (
        compute_diff_hash, get_cached_report_redis, set_cached_report_redis, find_cached_report
    )
    diff_hash = compute_diff_hash(repo.repo_full_name, full_diff)

    # 1. L1 Cache: Redis (< 0.5ms)
    redis_cached = await get_cached_report_redis(repo.id, diff_hash)
    if redis_cached:
        logger.info(f"⚡ [Redis L1 Cache Hit] Reusing cached LLM analysis for diff hash {diff_hash[:12]}...")
        existing_rep = await db.execute(select(Report).where(Report.commit_id == commit.id))
        report = existing_rep.scalar_one_or_none()

        if report:
            report.summary = redis_cached.get("summary", "")
            report.change_type = redis_cached.get("change_type", "unknown")
            report.risk_score = redis_cached.get("risk_score", 0.0)
            report.issues = redis_cached.get("issues", [])
            report.recommendations = redis_cached.get("recommendations", [])
            report.documentation_needed = redis_cached.get("documentation_needed", False)
            report.documentation_reason = redis_cached.get("documentation_reason", None)
            report.documentation_suggestion = redis_cached.get("documentation_suggestion", None)
            report.analysis_tier = redis_cached.get("analysis_tier", "multi_agent")
            report.analysis_gaps = redis_cached.get("analysis_gaps", [])
            report.whole_diff_skipped = redis_cached.get("whole_diff_skipped", False)
            report.scope_metrics = redis_cached.get("scope_metrics", {})
            report.blast_radius_mermaid = redis_cached.get("blast_radius_mermaid", None)
            report.diff_hash = diff_hash
        else:
            report = Report(
                commit_id=commit.id,
                summary=redis_cached.get("summary", ""),
                change_type=redis_cached.get("change_type", "unknown"),
                risk_score=redis_cached.get("risk_score", 0.0),
                issues=redis_cached.get("issues", []),
                recommendations=redis_cached.get("recommendations", []),
                documentation_needed=redis_cached.get("documentation_needed", False),
                documentation_reason=redis_cached.get("documentation_reason", None),
                documentation_suggestion=redis_cached.get("documentation_suggestion", None),
                analysis_tier=redis_cached.get("analysis_tier", "multi_agent"),
                analysis_gaps=redis_cached.get("analysis_gaps", []),
                whole_diff_skipped=redis_cached.get("whole_diff_skipped", False),
                scope_metrics=redis_cached.get("scope_metrics", {}),
                blast_radius_mermaid=redis_cached.get("blast_radius_mermaid", None),
                diff_hash=diff_hash,
            )
            db.add(report)

        commit.risk_score = redis_cached.get("risk_score", 0.0)
        await _update_status(db, commit, "completed", "Completed (Cached)")
        return

    # 2. L2 Cache: PostgreSQL DB (Durable Fallback)
    cached_report = await find_cached_report(db, repo.id, diff_hash)
    if cached_report:
        logger.info(f"⚡ [PostgreSQL L2 Cache Hit] Reusing cached LLM analysis for diff hash {diff_hash[:12]}...")
        existing_rep = await db.execute(select(Report).where(Report.commit_id == commit.id))
        report = existing_rep.scalar_one_or_none()

        report_dict = {
            "summary": cached_report.summary,
            "change_type": cached_report.change_type,
            "risk_score": cached_report.risk_score,
            "issues": cached_report.issues,
            "recommendations": cached_report.recommendations,
            "documentation_needed": cached_report.documentation_needed,
            "documentation_reason": getattr(cached_report, "documentation_reason", None),
            "documentation_suggestion": getattr(cached_report, "documentation_suggestion", None),
            "analysis_tier": cached_report.analysis_tier,
            "analysis_gaps": cached_report.analysis_gaps,
            "whole_diff_skipped": cached_report.whole_diff_skipped,
            "scope_metrics": cached_report.scope_metrics,
        }
        # Re-populate Redis L1 cache (warm-up)
        await set_cached_report_redis(repo.id, diff_hash, report_dict)

        if report:
            report.summary = cached_report.summary
            report.change_type = cached_report.change_type
            report.risk_score = cached_report.risk_score
            report.issues = cached_report.issues
            report.recommendations = cached_report.recommendations
            report.documentation_needed = cached_report.documentation_needed
            report.documentation_reason = getattr(cached_report, "documentation_reason", None)
            report.documentation_suggestion = getattr(cached_report, "documentation_suggestion", None)
            report.analysis_tier = cached_report.analysis_tier
            report.analysis_gaps = cached_report.analysis_gaps
            report.whole_diff_skipped = cached_report.whole_diff_skipped
            report.scope_metrics = cached_report.scope_metrics
            report.diff_hash = diff_hash
        else:
            report = Report(
                commit_id=commit.id,
                summary=cached_report.summary,
                change_type=cached_report.change_type,
                risk_score=cached_report.risk_score,
                issues=cached_report.issues,
                recommendations=cached_report.recommendations,
                documentation_needed=cached_report.documentation_needed,
                documentation_reason=getattr(cached_report, "documentation_reason", None),
                documentation_suggestion=getattr(cached_report, "documentation_suggestion", None),
                analysis_tier=cached_report.analysis_tier,
                analysis_gaps=cached_report.analysis_gaps,
                whole_diff_skipped=cached_report.whole_diff_skipped,
                scope_metrics=cached_report.scope_metrics,
                diff_hash=diff_hash,
            )
            db.add(report)

        commit.risk_score = cached_report.risk_score
        await _update_status(db, commit, "completed", "Completed (Cached)")
        return

    # status_callback is called concurrently from multiple LangGraph workers.
    # It MUST NOT share the main db session — concurrent db.commit() calls on
    # the same AsyncSession cause SQLAlchemy IllegalStateChangeError.
    # Solution: use a separate session + direct SQL UPDATE, serialized by a lock.
    _status_lock = asyncio.Lock()

    async def status_callback(detail: str):
        try:
            async with _status_lock:
                async with AsyncSessionLocal() as status_db:
                    from sqlalchemy import update
                    await status_db.execute(
                        update(Commit)
                        .where(Commit.id == commit.id)
                        .values(
                            status="retrying",
                            status_detail=detail,
                            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        )
                    )
                    await status_db.commit()
        except Exception as e:
            logger.debug(f"Status callback failed (non-critical): {e}")

    # Ensure repository dependencies are pre-indexed if not yet done
    from backend.models.file_dependency import FileDependency
    from backend.services.dependency_graph import index_repository_dependencies
    dep_check = await db.execute(select(FileDependency.id).where(FileDependency.repo_id == repo.id).limit(1))
    if not dep_check.scalar_one_or_none():
        try:
            await index_repository_dependencies(repo.id, repo.repo_full_name, pat, repo.branch)
        except Exception as idx_e:
            logger.warning(f"Repository pre-indexing non-critical warning: {idx_e}")

    initial_state = {
        "repo_id": repo.id,
        "repo_name": repo.repo_full_name,
        "branch": repo.branch,
        "commit_message": commit.message,
        "full_diff": full_diff,
        "file_chunks": {},
        "file_tiers": {},
        "total_changed_lines": 0,
        "whole_diff_agents_skipped": False,
        "github_pat": pat,                       # Phase 4: Tree-sitter context (decrypted)
        "commit_sha": commit.sha,               # Phase 4: Tree-sitter context
        "context_snippets": {},                  # Phase 4: Tree-sitter context
        "interface_change_summary": None,       # Phase 4: Interface caching
        "change_classification": None,
        "breaking_change": None,
        "documentation_impact": None,
        "security_issues": [], "quality_issues": [], "bug_issues": [],
        "analysis_gaps": [],
        "deduped_issues": None,
        "risk_score": None,
        "final_summary": None,
        "final_recommendations": None,
        "analysis_scope": {},
        "status_callback": status_callback,
    }

    result = await analysis_graph.ainvoke(initial_state)

    # Entire commit only contained skip-tier files (docs/assets/lockfiles)
    if not result["file_chunks"] and not result["whole_diff_agents_skipped"]:
        commit.skip_reason = "No analysis needed — commit only contains " \
                              "documentation, asset, or lockfile changes."
        commit.status = "skipped"
        commit.status_detail = commit.skip_reason
        commit.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

        existing_rep = await db.execute(select(Report).where(Report.commit_id == commit.id))
        report = existing_rep.scalar_one_or_none()
        scope_metrics = result.get("scope_metrics") or {}
        report_dict = {
            "summary": commit.skip_reason,
            "change_type": "docs",
            "risk_score": 0.0,
            "issues": [],
            "recommendations": [],
            "documentation_needed": False,
            "documentation_reason": None,
            "documentation_suggestion": None,
            "analysis_tier": "skipped",
            "scope_metrics": scope_metrics,
        }
        await set_cached_report_redis(repo.id, diff_hash, report_dict)

        if report:
            report.summary = commit.skip_reason
            report.change_type = "docs"
            report.risk_score = 0.0
            report.issues = []
            report.recommendations = []
            report.documentation_needed = False
            report.documentation_reason = None
            report.documentation_suggestion = None
            report.analysis_tier = "skipped"
            report.scope_metrics = scope_metrics
            report.diff_hash = diff_hash
        else:
            report = Report(
                commit_id=commit.id,
                summary=commit.skip_reason,
                change_type="docs",
                risk_score=0.0,
                issues=[],
                recommendations=[],
                documentation_needed=False,
                documentation_reason=None,
                documentation_suggestion=None,
                analysis_tier="skipped",
                scope_metrics=scope_metrics,
                diff_hash=diff_hash,
            )
            db.add(report)
        await db.commit()
        return

    # In-place upsert for Report: update existing if present, otherwise insert new
    existing_rep = await db.execute(select(Report).where(Report.commit_id == commit.id))
    report = existing_rep.scalar_one_or_none()

    issues_dump = [
        i.model_dump() if hasattr(i, "model_dump") else i
        for i in (result["deduped_issues"] or [])
    ]

    doc_impact = result.get("documentation_impact")
    doc_needed = doc_impact.documentation_needed if doc_impact else False
    doc_reason = doc_impact.reason if doc_impact else None
    doc_suggestion = doc_impact.suggestion if doc_impact else None

    blast_radius_mermaid = None
    scope_metrics = result.get("scope_metrics") or {}
    analyzed_files = scope_metrics.get("analyzed_files", [])
    primary_filepath = analyzed_files[0].get("filepath") if (analyzed_files and isinstance(analyzed_files[0], dict)) else None

    if primary_filepath:
        try:
            transitive_map = await get_transitive_importers(repo.id, primary_filepath, max_depth=3)
            blast_radius_mermaid = generate_blast_radius_mermaid(primary_filepath, transitive_map, issues_dump)
        except Exception as ex:
            logger.warning(f"Failed to generate blast radius diagram: {ex}")

    report_dict = {
        "summary": result["final_summary"] or "",
        "change_type": result["change_classification"].change_type if result["change_classification"] else "unknown",
        "risk_score": result["risk_score"] or 0.0,
        "issues": issues_dump,
        "recommendations": result["final_recommendations"] or [],
        "documentation_needed": doc_needed,
        "documentation_reason": doc_reason,
        "documentation_suggestion": doc_suggestion,
        "analysis_tier": "multi_agent",
        "analysis_gaps": result["analysis_gaps"],
        "whole_diff_skipped": result["whole_diff_agents_skipped"],
        "scope_metrics": scope_metrics,
        "blast_radius_mermaid": blast_radius_mermaid,
    }
    await set_cached_report_redis(repo.id, diff_hash, report_dict)

    if report:
        report.summary = result["final_summary"] or ""
        report.change_type = result["change_classification"].change_type if result["change_classification"] else "unknown"
        report.risk_score = result["risk_score"] or 0.0
        report.issues = issues_dump
        report.recommendations = result["final_recommendations"] or []
        report.documentation_needed = doc_needed
        report.documentation_reason = doc_reason
        report.documentation_suggestion = doc_suggestion
        report.analysis_tier = "multi_agent"
        report.analysis_gaps = result["analysis_gaps"]
        report.whole_diff_skipped = result["whole_diff_agents_skipped"]
        report.scope_metrics = result.get("scope_metrics") or {}
        report.blast_radius_mermaid = blast_radius_mermaid
        report.diff_hash = diff_hash
    else:
        report = Report(
            commit_id=commit.id,
            summary=result["final_summary"] or "",
            change_type=result["change_classification"].change_type if result["change_classification"] else "unknown",
            risk_score=result["risk_score"] or 0.0,
            issues=issues_dump,
            recommendations=result["final_recommendations"] or [],
            documentation_needed=doc_needed,
            documentation_reason=doc_reason,
            documentation_suggestion=doc_suggestion,
            analysis_tier="multi_agent",
            analysis_gaps=result["analysis_gaps"],
            whole_diff_skipped=result["whole_diff_agents_skipped"],
            scope_metrics=result.get("scope_metrics") or {},
            blast_radius_mermaid=blast_radius_mermaid,
            diff_hash=diff_hash,
        )
        db.add(report)

    commit.risk_score = result["risk_score"]

    await create_notifications_for_multiagent_report(db, commit.id, result)
    await _update_status(db, commit, "completed")



async def _reanalyze_commit_bg(repo_id: int, commit_id: int):
    """
    Background-task entry point for retries. Opens its OWN fresh
    AsyncSessionLocal() rather than reusing the request-scoped session
    from the /retry endpoint — that session closes the instant the HTTP
    response is returned, so passing it into a background task would
    hand _analyze_commit an already-closed session and fail at the
    first query. Same pattern process_push_event already uses for the
    same reason.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Commit, ConnectedRepo)
            .join(ConnectedRepo, ConnectedRepo.id == Commit.repo_id)
            .where(Commit.id == commit_id, ConnectedRepo.id == repo_id)
        )
        row = result.first()
        if not row:
            logger.error(f"[retry] Commit {commit_id} or repo {repo_id} not found "
                         f"during background retry — may have been deleted after queuing.")
            return

        commit, repo = row
        commit_sha = commit.sha[:7] if commit.sha else "unknown"

        try:
            await _analyze_commit(db, repo, commit)
        except Exception as e:
            logger.error(f"[retry] Unhandled exception re-analyzing "
                         f"{commit_sha}: {e}", exc_info=True)
            try:
                await db.rollback()
                commit.status = "failed"
                commit.status_detail = f"Retry failed: {type(e).__name__}: {str(e)[:200]}"
                await db.commit()
            except Exception as db_error:
                logger.error(f"[retry] Could not record retry-failure status "
                             f"for {commit_sha}: {db_error}")

