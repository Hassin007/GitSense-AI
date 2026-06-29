import httpx
from fastapi import HTTPException
from backend.config import settings


GITHUB_API = "https://api.github.com"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"


# ── OAuth ─────────────────────────────────────────────────────────────────────

async def exchange_code_for_token(code: str) -> str:
    """Exchange the OAuth code GitHub sends us for a real access token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GITHUB_OAUTH_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id":     settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code":          code,
            }
        )
    data = response.json()
    if "access_token" not in data:
        raise HTTPException(status_code=400, detail=f"GitHub OAuth failed: {data.get('error_description', 'unknown error')}")
    return data["access_token"]


async def get_github_user(access_token: str) -> dict:
    """Fetch the authenticated user's GitHub profile."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_API}/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            }
        )
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch GitHub user profile.")
    return response.json()


# ── Repository Validation ─────────────────────────────────────────────────────

async def validate_repo_access(pat: str, repo_full_name: str) -> dict:
    """
    Verify the PAT has access to the repo.
    Returns repo metadata if valid, raises HTTPException if not.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_API}/repos/{repo_full_name}",
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github+json",
            }
        )
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_full_name}' not found or PAT has no access.")
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid GitHub Personal Access Token.")
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Could not verify repository access.")
    return response.json()


# ── Webhook Registration ──────────────────────────────────────────────────────

async def register_webhook(pat: str, repo_full_name: str) -> int:
    """
    Register a push webhook on the repository.
    Returns the GitHub webhook ID (store this to delete later).
    """
    webhook_url = f"{settings.webhook_base_url}/webhook"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_API}/repos/{repo_full_name}/hooks",
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "name": "web",
                "active": True,
                "events": ["push"],
                "config": {
                    "url":          webhook_url,
                    "content_type": "json",
                    "secret":       settings.github_webhook_secret,
                    "insecure_ssl": "0",
                }
            }
        )

    if response.status_code == 422:
        # Webhook already exists on this repo
        raise HTTPException(status_code=422, detail="A webhook is already registered on this repository.")
    if response.status_code not in (200, 201):
        raise HTTPException(status_code=400, detail=f"Failed to register webhook: {response.text}")

    return response.json()["id"]


async def delete_webhook(pat: str, repo_full_name: str, webhook_id: int) -> None:
    """Remove a previously registered webhook (used when user disconnects a repo)."""
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{GITHUB_API}/repos/{repo_full_name}/hooks/{webhook_id}",
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github+json",
            }
        )


# ── Diff Fetching ─────────────────────────────────────────────────────────────

async def fetch_commit_diff(pat: str, repo_full_name: str, commit_sha: str) -> str:
    """
    Fetch the raw Git diff for a single commit.
    Note: This is fetched on-demand only — never stored in the database.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_API}/repos/{repo_full_name}/commits/{commit_sha}",
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github.diff",   # returns raw diff format
            }
        )
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Could not fetch diff for commit {commit_sha}.")
    return response.text
