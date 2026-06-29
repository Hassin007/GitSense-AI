from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models.repo import ConnectedRepo
from backend.models.commit import Commit
from backend.services.security import verify_github_signature
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])


# ── Diff Size Policy ──────────────────────────────────────────────────────────

MAX_DIFF_CHARS = 12_000  # ~3,000 tokens — context limit for free tier LLM

class DiffTooLargeError(Exception):
    def __init__(self, char_count: int, limit: int):
        self.char_count = char_count
        self.limit = limit
        self.message = (
            f"Diff too large: {char_count:,} characters (limit is {limit:,}). "
            f"Consider breaking this commit into smaller, focused commits."
        )
        super().__init__(self.message)


# ── Webhook Receiver ──────────────────────────────────────────────────────────

@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    GitHub push event receiver.

    IMPORTANT: This endpoint must respond in under 10 seconds.
    All heavy work is delegated to a background task.
    """

    # 1. Validate GitHub signature FIRST — reject fakes immediately
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    verify_github_signature(body, signature)

    # 2. Parse payload
    payload = await request.json()
    event_type = request.headers.get("X-GitHub-Event", "")

    # We only care about push events
    if event_type != "push":
        return {"status": "ignored", "reason": f"Event type '{event_type}' not handled."}

    # Extract repository info
    repo_full_name = payload.get("repository", {}).get("full_name")
    ref = payload.get("ref", "")  # e.g. "refs/heads/main"
    commits = payload.get("commits", [])

    if not commits:
        return {"status": "ignored", "reason": "No commits in payload."}

    # 3. Look up the connected repo in our database
    result = await db.execute(
        select(ConnectedRepo).where(ConnectedRepo.repo_full_name == repo_full_name)
    )
    repo = result.scalar_one_or_none()

    if not repo:
        return {"status": "ignored", "reason": "Repository not registered in GitSense."}

    # 4. Check branch matches
    branch_from_ref = ref.replace("refs/heads/", "")
    if branch_from_ref != repo.branch:
        return {"status": "ignored", "reason": f"Push to '{branch_from_ref}', monitoring '{repo.branch}'."}

    # 5. Queue analysis as background task — return immediately to GitHub
    background_tasks.add_task(process_push_event, payload, repo, db)

    return {"status": "received", "commits": len(commits)}


# ── Background Task ───────────────────────────────────────────────────────────

async def process_push_event(payload: dict, repo: ConnectedRepo, db: AsyncSession):
    """
    Background processing for a GitHub push event.
    Stores each commit record with status 'pending'.
    (Week 2 will add: diff fetch → LLM analysis → report storage)
    """
    commits_data = payload.get("commits", [])

    for commit_data in commits_data:
        sha = commit_data.get("id")
        message = commit_data.get("message", "")
        author = commit_data.get("author", {}).get("name", "unknown")
        timestamp_str = commit_data.get("timestamp")

        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except Exception:
            timestamp = datetime.now(timezone.utc)

        # Store commit with 'pending' status
        # Week 2 will update this to 'completed', 'skipped', or 'failed'
        commit = Commit(
            repo_id=repo.id,
            sha=sha,
            message=message,
            author=author,
            timestamp=timestamp,
            status="pending",
        )
        db.add(commit)

        logger.info(f"Queued commit {sha[:7]} from {repo.repo_full_name} for analysis.")

    await db.commit()
