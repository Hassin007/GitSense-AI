from sqlalchemy.ext.asyncio import AsyncSession
from backend.models.notification import Notification
from backend.schemas.analysis import CommitAnalysis


HIGH_RISK_THRESHOLD = 8.0


async def create_notifications_for_report(
    db: AsyncSession, commit_id: int, analysis: CommitAnalysis
) -> None:
    """
    Only notify for important events — avoids alert fatigue.
    Rules:
      - risk_score >= 8.0           → high_risk_commit
      - any issue severity=critical → critical_security
      - change_type is a breaking indicator handled by issue detection
    """
    notes = []

    if analysis.risk_score >= HIGH_RISK_THRESHOLD:
        notes.append(Notification(
            commit_id=commit_id,
            kind="high_risk_commit",
            message=f"High-risk commit detected. Risk Score: {analysis.risk_score}/10. {analysis.summary}"
        ))

    for issue in analysis.issues:
        if issue.severity == "critical":
            notes.append(Notification(
                commit_id=commit_id,
                kind="critical_security",
                message=f"Critical issue: {issue.title} — {issue.explanation}"
            ))

    for note in notes:
        db.add(note)

    if notes:
        await db.commit()


async def create_notifications_for_multiagent_report(
    db: AsyncSession, commit_id: int, result: dict
) -> None:
    """
    Phase 3: notification creation for the multi-agent result shape.
    Handles breaking changes, analysis gaps, and deduped issues as
    Pydantic objects (not dicts).
    """
    notes = []

    if (result["risk_score"] or 0) >= HIGH_RISK_THRESHOLD:
        notes.append(Notification(
            commit_id=commit_id, kind="high_risk_commit",
            message=f"High-risk commit detected. Risk Score: {result['risk_score']}/10."
        ))

    for issue in (result["deduped_issues"] or []):
        if issue.severity == "critical":
            notes.append(Notification(
                commit_id=commit_id, kind="critical_security",
                message=f"Critical issue: {issue.title} ({issue.filepath}) — {issue.explanation}"
            ))

    if result.get("breaking_change") and result["breaking_change"].is_breaking:
        notes.append(Notification(
            commit_id=commit_id, kind="breaking_change",
            message=f"Breaking change detected: {result['breaking_change'].reason}"
        ))

    for gap in result.get("analysis_gaps", []):
        notes.append(Notification(
            commit_id=commit_id, kind="analysis_gap",
            message=gap
        ))

    for note in notes:
        db.add(note)
    if notes:
        await db.commit()


async def create_skip_notification(db: AsyncSession, commit_id: int, reason: str) -> None:
    note = Notification(commit_id=commit_id, kind="diff_too_large", message=reason)
    db.add(note)
    await db.commit()


async def create_failure_notification(db: AsyncSession, commit_id: int, reason: str) -> None:
    note = Notification(commit_id=commit_id, kind="analysis_failed", message=reason)
    db.add(note)
    await db.commit()
