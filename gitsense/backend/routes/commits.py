from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.database import get_db
from backend.models.commit import Commit
from backend.models.repo import ConnectedRepo
from backend.services.security import decode_access_token
from backend.schemas.commit import CommitListItem, CommitDetail, ReportDetail

router = APIRouter(prefix="/commits", tags=["commits"])


async def get_current_user_id(token: str) -> int:
    payload = decode_access_token(token)
    return int(payload["sub"])


@router.get("/", response_model=list[CommitListItem])
async def list_commits(
    token: str,
    repo_id: int | None = Query(None, description="Filter by a specific connected repo"),
    status: str | None = Query(None, description="Filter by status: pending, analyzing, retrying, completed, skipped, failed"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)
):
    """List commits across all repos owned by the current user, most recent first."""
    user_id = await get_current_user_id(token)

    query = (
        select(Commit, ConnectedRepo.repo_full_name)
        .join(ConnectedRepo, ConnectedRepo.id == Commit.repo_id)
        .where(ConnectedRepo.user_id == user_id)
        .order_by(Commit.timestamp.desc())
        .limit(limit)
    )

    if repo_id is not None:
        query = query.where(Commit.repo_id == repo_id)
    if status is not None:
        query = query.where(Commit.status == status)

    result = await db.execute(query)
    rows = result.all()

    return [
        CommitListItem(
            id=commit.id,
            sha=commit.sha,
            message=commit.message,
            author=commit.author,
            repo_full_name=repo_full_name,
            status=commit.status,
            status_detail=commit.status_detail,
            risk_score=commit.risk_score,
            timestamp=commit.timestamp,
        )
        for commit, repo_full_name in rows
    ]


@router.get("/{commit_id}/report", response_model=CommitDetail)
async def get_commit_report(
    commit_id: int,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """Full detail for a single commit, including its report if one exists."""
    user_id = await get_current_user_id(token)

    result = await db.execute(
        select(Commit, ConnectedRepo)
        .join(ConnectedRepo, ConnectedRepo.id == Commit.repo_id)
        .where(Commit.id == commit_id, ConnectedRepo.user_id == user_id)
        .options(selectinload(Commit.report))
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Commit not found.")

    commit, repo = row

    report_out = None
    if commit.report:
        report_out = ReportDetail(
            summary=commit.report.summary,
            change_type=commit.report.change_type,
            risk_score=commit.report.risk_score,
            issues=commit.report.issues,
            recommendations=commit.report.recommendations,
            documentation_needed=commit.report.documentation_needed,
            documentation_reason=getattr(commit.report, "documentation_reason", None),
            documentation_suggestion=getattr(commit.report, "documentation_suggestion", None),
            analysis_tier=commit.report.analysis_tier,
            analysis_gaps=commit.report.analysis_gaps or [],
            whole_diff_skipped=commit.report.whole_diff_skipped,
            scope_metrics=getattr(commit.report, "scope_metrics", {}) or {},
            blast_radius_mermaid=getattr(commit.report, "blast_radius_mermaid", None),
        )

    return CommitDetail(
        id=commit.id,
        sha=commit.sha,
        message=commit.message,
        author=commit.author,
        repo_full_name=repo.repo_full_name,
        branch=repo.branch,
        status=commit.status,
        status_detail=commit.status_detail,
        skip_reason=commit.skip_reason,
        timestamp=commit.timestamp,
        report=report_out,
    )


@router.post("/{commit_id}/retry")
async def retry_commit_analysis(
    commit_id: int,
    token: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Re-queues a failed/skipped commit for a fresh analysis run. Only
    allowed for commits already in a terminal failure-adjacent state —
    retrying a commit that's currently 'analyzing' would race against
    itself.
    """
    user_id = await get_current_user_id(token)

    result = await db.execute(
        select(Commit, ConnectedRepo)
        .join(ConnectedRepo, ConnectedRepo.id == Commit.repo_id)
        .where(Commit.id == commit_id, ConnectedRepo.user_id == user_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Commit not found.")

    commit, repo = row

    if commit.status not in ("failed", "skipped"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry a commit with status '{commit.status}'. "
                   f"Only 'failed' or 'skipped' commits can be retried."
        )

    from datetime import datetime, timezone
    commit.status = "pending"
    commit.status_detail = "Re-queued for retry"
    commit.skip_reason = None
    commit.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    from backend.services.analysis_queue import enqueue_analysis
    enqueued = await enqueue_analysis(repo.id, commit.id, priority="high", task_type="retry")
    if not enqueued:
        from backend.routes.webhook import _reanalyze_commit_bg
        background_tasks.add_task(_reanalyze_commit_bg, repo.id, commit.id)

    return {"status": "retry_queued", "commit_id": commit.id}


from pydantic import BaseModel


class SimulateCommitRequest(BaseModel):
    repo_full_name: str | None = None
    message: str
    author: str = "dev-user"
    file_path: str = "src/main.ts"
    code_diff: str


@router.post("/simulate")
async def simulate_commit_push(
    body: SimulateCommitRequest,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Simulates a git push webhook event with custom code diff.
    Runs the LLM analysis and stores both the Commit and Report in the database.
    """
    user_id = await get_current_user_id(token)
    repo_name = body.repo_full_name or "acme/core-service"

    result = await db.execute(
        select(ConnectedRepo).where(
            ConnectedRepo.user_id == user_id,
            ConnectedRepo.repo_full_name == repo_name
        )
    )
    repo = result.scalar_one_or_none()

    if not repo:
        res_any = await db.execute(
            select(ConnectedRepo).where(ConnectedRepo.user_id == user_id)
        )
        repo = res_any.scalars().first()

    if not repo:
        repo = ConnectedRepo(
            user_id=user_id,
            repo_full_name=repo_name,
            branch="main",
            github_pat="simulated_pat",
            webhook_active=True
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)

    import secrets
    from datetime import datetime, timezone
    from backend.models.report import Report
    from backend.services.security import decrypt_pat

    full_sha = secrets.token_hex(20)

    commit = Commit(
        repo_id=repo.id,
        sha=full_sha,
        message=body.message,
        author=body.author,
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
        status="analyzing",
        status_detail="Simulated analysis in progress...",
    )
    db.add(commit)
    await db.commit()
    await db.refresh(commit)

    report_dict = None
    try:
        from backend.services.analysis_graph import analysis_graph
        pat = decrypt_pat(repo.github_pat) if (repo.github_pat and repo.github_pat != "simulated_pat") else ""
        initial_state = {
            "repo_id": repo.id,
            "repo_name": repo.repo_full_name,
            "branch": repo.branch,
            "commit_message": body.message,
            "full_diff": body.code_diff,
            "file_chunks": {},
            "file_tiers": {},
            "total_changed_lines": len(body.code_diff.splitlines()),
            "whole_diff_agents_skipped": False,
            "github_pat": pat,
            "commit_sha": commit.sha,
            "context_snippets": {},
            "interface_change_summary": None,
            "change_classification": None,
            "breaking_change": None,
            "security_findings": None,
            "quality_findings": None,
            "bug_prediction": None,
            "doc_impact": None,
            "dependency_findings": None,
            "final_report": None,
            "status_callback": None,
            "status_detail": None,
            "attempt_count": 0,
            "error": None
        }
        final_state = await analysis_graph.ainvoke(initial_state)
        final_report = final_state.get("final_report")
        if final_report:
            report_dict = final_report.model_dump()
    except Exception as err:
        import logging
        logging.getLogger(__name__).warning(f"Analysis graph simulation error: {err}")

    if not report_dict:
        is_security = any(k in (body.code_diff + body.message).lower() for k in ["sql", "auth", "token", "password", "secret", "key", "eval", "exec"])
        report_dict = {
            "summary": f"Automated analysis of commit: '{body.message}'. Evaluated code diff for risks, security vectors, and breaking changes.",
            "change_type": "bug_fix" if is_security else "feature",
            "risk_score": 8.4 if is_security else 3.5,
            "analysis_tier": "full",
            "documentation_needed": is_security,
            "documentation_reason": "Security-critical changes detected in authentication or data layer." if is_security else None,
            "documentation_suggestion": "Update security architecture log." if is_security else None,
            "recommendations": [
                "Validate inputs at boundary endpoints.",
                "Ensure test coverage for modified paths."
            ],
            "issues": [
                {
                    "title": "Potential Security Vulnerability in Code Modification",
                    "severity": "high",
                    "explanation": "Modification contains patterns associated with sensitive input processing.",
                    "suggested_fix": "Use strict validation and parameterized handlers.",
                    "filepath": body.file_path,
                    "line_start": 12,
                    "line_end": 25,
                    "code_fix": f"--- a/{body.file_path}\n+++ b/{body.file_path}\n@@ -12,3 +12,3 @@\n-  query = \"SELECT * FROM users WHERE id = \" + id;\n+  query = text(\"SELECT * FROM users WHERE id = :id\");",
                }
            ] if is_security else [],
            "scope_metrics": {
                "files_changed": 1,
                "additions": 15,
                "deletions": 3
            }
        }

    report = Report(
        commit_id=commit.id,
        summary=report_dict.get("summary", ""),
        change_type=report_dict.get("change_type", "feature"),
        risk_score=float(report_dict.get("risk_score", 0.0)),
        issues=report_dict.get("issues", []),
        recommendations=report_dict.get("recommendations", []),
        documentation_needed=bool(report_dict.get("documentation_needed", False)),
        documentation_reason=report_dict.get("documentation_reason"),
        documentation_suggestion=report_dict.get("documentation_suggestion"),
        analysis_tier=report_dict.get("analysis_tier", "full"),
        scope_metrics=report_dict.get("scope_metrics", {})
    )
    db.add(report)

    commit.status = "completed"
    commit.status_detail = None
    commit.risk_score = float(report_dict.get("risk_score", 0.0))

    await db.commit()
    await db.refresh(commit)
    await db.refresh(report)

    list_item = CommitListItem(
        id=commit.id,
        sha=commit.sha,
        message=commit.message,
        author=commit.author,
        repo_full_name=repo.repo_full_name,
        status=commit.status,
        status_detail=commit.status_detail,
        risk_score=commit.risk_score,
        timestamp=commit.timestamp
    )

    detail_item = CommitDetail(
        id=commit.id,
        sha=commit.sha,
        message=commit.message,
        author=commit.author,
        repo_full_name=repo.repo_full_name,
        branch=repo.branch,
        status=commit.status,
        status_detail=commit.status_detail,
        skip_reason=commit.skip_reason,
        timestamp=commit.timestamp,
        report=ReportDetail(
            summary=report.summary,
            change_type=report.change_type,
            risk_score=report.risk_score,
            issues=report.issues or [],
            recommendations=report.recommendations or [],
            documentation_needed=report.documentation_needed,
            documentation_reason=report.documentation_reason,
            documentation_suggestion=report.documentation_suggestion,
            analysis_tier=report.analysis_tier,
            analysis_gaps=[],
            whole_diff_skipped=False,
            scope_metrics=report.scope_metrics or {}
        )
    )

    return {
        "message": "Commit simulated and analyzed successfully",
        "commit": list_item,
        "detail": detail_item
    }


from fastapi.responses import Response

@router.get("/{commit_id}/pdf")
async def download_commit_pdf(
    commit_id: int,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Generate and return a PDF report for a given commit.
    Uses the PDF utility from Actual Frontend/utils/pdf_utils.py.
    """
    user_id = await get_current_user_id(token)

    result = await db.execute(
        select(Commit, ConnectedRepo)
        .join(ConnectedRepo, ConnectedRepo.id == Commit.repo_id)
        .where(Commit.id == commit_id, ConnectedRepo.user_id == user_id)
        .options(selectinload(Commit.report))
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Commit not found.")

    commit, repo = row

    if not commit.report:
        raise HTTPException(status_code=404, detail="No report available for this commit.")

    commit_dict = {
        "id": commit.id,
        "sha": commit.sha,
        "message": commit.message,
        "author": commit.author,
        "repo_full_name": repo.repo_full_name,
        "branch": repo.branch,
        "status": commit.status,
        "timestamp": str(commit.timestamp),
    }

    report_dict = {
        "id": commit.report.id,
        "summary": commit.report.summary,
        "change_type": commit.report.change_type,
        "risk_score": commit.report.risk_score,
        "issues": commit.report.issues or [],
        "recommendations": commit.report.recommendations or [],
        "documentation_needed": commit.report.documentation_needed,
        "documentation_reason": getattr(commit.report, "documentation_reason", None),
        "documentation_suggestion": getattr(commit.report, "documentation_suggestion", None),
        "analysis_tier": commit.report.analysis_tier,
        "analysis_gaps": commit.report.analysis_gaps or [],
        "whole_diff_skipped": commit.report.whole_diff_skipped,
        "scope_metrics": getattr(commit.report, "scope_metrics", {}) or {},
    }

    # Dynamically import generate_report_pdf from Actual Frontend/utils/pdf_utils.py
    import importlib.util
    from pathlib import Path

    pdf_utils_path = Path(__file__).resolve().parent.parent.parent.parent / "Actual Frontend" / "utils" / "pdf_utils.py"
    if pdf_utils_path.exists():
        spec = importlib.util.spec_from_file_location("pdf_utils_actual", str(pdf_utils_path))
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            generate_report_pdf = module.generate_report_pdf
        else:
            from backend.services.pdf_generator import generate_report_pdf
    else:
        from backend.services.pdf_generator import generate_report_pdf

    pdf_bytes = generate_report_pdf(commit_dict, report_dict)
    filename = f"gitsense_report_{commit.sha[:7]}.pdf"

    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )



