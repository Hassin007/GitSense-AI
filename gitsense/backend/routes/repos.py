from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models.repo import ConnectedRepo
from backend.services.github import validate_repo_access, register_webhook, delete_webhook
from backend.services.security import decode_access_token, encrypt_pat, decrypt_pat
from pydantic import BaseModel

router = APIRouter(prefix="/repos", tags=["repos"])


# ── Dependency: extract user_id from token ────────────────────────────────────

async def get_current_user_id(token: str) -> int:
    payload = decode_access_token(token)
    return int(payload["sub"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ConnectRepoRequest(BaseModel):
    github_pat:     str   # Personal Access Token
    repo_full_name: str   # e.g. "username/my-project"
    branch:         str = "main"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/connect")
async def connect_repo(
    body: ConnectRepoRequest,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Connect a GitHub repository.
    Steps:
      1. Validate the PAT has access to the repo
      2. Register a GitHub push webhook
      3. Store the repo configuration
    """
    user_id = await get_current_user_id(token)

    # 1. Validate PAT + repo access
    repo_data = await validate_repo_access(body.github_pat, body.repo_full_name)

    # 2. Check if this user already has this repo connected.
    # If so, this is a RECONNECT (e.g. new machine, rotated ngrok URL) —
    # update the existing record rather than blocking with a 409.
    existing_result = await db.execute(
        select(ConnectedRepo).where(
            ConnectedRepo.user_id == user_id,
            ConnectedRepo.repo_full_name == body.repo_full_name
        )
    )
    existing_repo = existing_result.scalar_one_or_none()

    # 3. Register or repoint webhook (idempotent — safe to call every time)
    webhook_id, was_repointed = await register_webhook(body.github_pat, body.repo_full_name)

    # 4. Store or update in database with encrypted PAT at rest
    encrypted_pat = encrypt_pat(body.github_pat)
    if existing_repo:
        existing_repo.branch = body.branch
        existing_repo.github_pat = encrypted_pat
        existing_repo.webhook_id = webhook_id
        existing_repo.webhook_active = True
        repo = existing_repo
    else:
        repo = ConnectedRepo(
            user_id=user_id,
            repo_full_name=body.repo_full_name,
            branch=body.branch,
            github_pat=encrypted_pat,
            webhook_id=webhook_id,
            webhook_active=True,
        )
        db.add(repo)

    await db.commit()
    await db.refresh(repo)

    message = (
        f"Repository '{body.repo_full_name}' reconnected — webhook repointed to current backend."
        if was_repointed
        else f"Repository '{body.repo_full_name}' connected successfully."
    )

    return {
        "message": message,
        "repo_id": repo.id,
        "webhook_id": webhook_id,
        "branch": body.branch,
        "was_repointed": was_repointed,
    }


@router.get("/")
async def list_repos(token: str, db: AsyncSession = Depends(get_db)):
    """Return all repos connected by the current user."""
    user_id = await get_current_user_id(token)
    result = await db.execute(
        select(ConnectedRepo).where(ConnectedRepo.user_id == user_id)
    )
    repos = result.scalars().all()
    return [
        {
            "id": r.id,
            "repo_full_name": r.repo_full_name,
            "branch": r.branch,
            "webhook_active": r.webhook_active,
            "created_at": r.created_at.isoformat(),
        }
        for r in repos
    ]


@router.delete("/{repo_id}")
async def disconnect_repo(repo_id: int, token: str, db: AsyncSession = Depends(get_db)):
    """Disconnect a repo — removes the GitHub webhook and deletes the record."""
    user_id = await get_current_user_id(token)
    result = await db.execute(
        select(ConnectedRepo).where(
            ConnectedRepo.id == repo_id,
            ConnectedRepo.user_id == user_id
        )
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")

    # Remove the webhook from GitHub
    if repo.webhook_id:
        pat = decrypt_pat(repo.github_pat)
        await delete_webhook(pat, repo.repo_full_name, repo.webhook_id)

    await db.delete(repo)
    await db.commit()
    return {"message": f"Repository '{repo.repo_full_name}' disconnected."}
